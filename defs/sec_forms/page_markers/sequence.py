"""Namespace-aware sequence validation and conservative healing."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise
from statistics import median

from .models import InferredBoundary, PageCandidate, PageNumberRun

# Upper bound on pages interpolated across one value gap. Larger jumps are
# typically foreign values (years, totals) inside the run, not missing pages.
MAX_INTERPOLATED_GAP = 64


def monotone_fraction(values: Iterable[int], max_delta: int = 3) -> float:
    """Return the fraction of consecutive values forming a bounded increase."""

    numbers = list(values)
    if len(numbers) < 2:
        return 0.0
    good = sum(0 < right - left <= max_delta for left, right in pairwise(numbers))
    return good / (len(numbers) - 1)


def _alignment_fraction(candidates: list[PageCandidate]) -> float:
    if not candidates:
        return 0.0
    counts: dict[int, int] = {}
    for candidate in candidates:
        bucket = candidate.leading_column // 2
        counts[bucket] = counts.get(bucket, 0) + 1
    return max(counts.values()) / len(candidates)


def _run_stats(candidates: list[PageCandidate]) -> tuple[float, float]:
    gaps = [right.start_line - left.start_line for left, right in pairwise(candidates)]
    if not gaps:
        return 0.0, 0.0
    return sum(gaps) / len(gaps), float(median(gaps))


def validate_group(
    candidates: Iterable[PageCandidate],
    *,
    strategy: str,
    min_members: int = 3,
    min_monotone: float = 0.8,
    min_gap_median: float = 0.0,
) -> PageNumberRun | None:
    """Validate one same-family/namespace candidate group."""

    ordered = sorted(candidates, key=lambda item: (item.start_line, item.start))
    if len(ordered) < min_members:
        return None
    mono = monotone_fraction(item.value for item in ordered)
    gap_mean, gap_median = _run_stats(ordered)
    if mono < min_monotone or gap_median < min_gap_median:
        return None
    return PageNumberRun(
        family=ordered[0].family,
        namespace=ordered[0].namespace,
        candidates=tuple(ordered),
        monotone_fraction=mono,
        gap_mean=gap_mean,
        gap_median=gap_median,
        alignment_fraction=_alignment_fraction(ordered),
        source_start_line=ordered[0].start_line,
        source_end_line=ordered[-1].end_line,
        strategy=strategy,
    )


def _is_detour(
    left: PageCandidate, middle: PageCandidate, right: PageCandidate
) -> bool:
    return right.value > left.value and middle.value > right.value


def _repair_sequence(
    members: list[PageCandidate],
) -> tuple[list[PageCandidate], list[PageCandidate]]:
    """Pop spikes, dips, duplicates, and inversions from one slot's sequence.

    A middle value must sit strictly between ascending endpoints. Descending
    endpoints (inversions such as a foreign table total followed by a
    duplicate restart) are repaired only when the surrounding context is
    ascending; restart-like descents, where the right side continues
    consecutively, are left intact for section handling.
    """
    members = list(members)
    popped: list[PageCandidate] = []
    changed = True
    while changed and len(members) >= 3:
        changed = False
        for index in range(1, len(members) - 1):
            left, middle, right = (
                members[index - 1],
                members[index],
                members[index + 1],
            )
            if left.value < right.value:
                if left.value < middle.value < right.value:
                    continue
                popped.append(members.pop(index))
                changed = True
                break
            if left.value == right.value:
                if middle.value == left.value:
                    continue
                popped.append(members.pop(index))
                changed = True
                break
            # Inversion: left.value > right.value.
            previous = members[index - 2] if index >= 2 else None
            following = members[index + 2] if index + 2 < len(members) else None
            if following is not None and following.value == right.value + 1:
                # Restart-like descent: the right side continues consecutively.
                continue
            duplicate_counts: dict[int, int] = {}
            for candidate in members:
                duplicate_counts[candidate.value] = (
                    duplicate_counts.get(candidate.value, 0) + 1
                )
            if duplicate_counts.get(middle.value, 0) > 1:
                popped.append(members.pop(index))
            elif duplicate_counts.get(right.value, 0) > 1:
                popped.append(members.pop(index + 1))
            else:
                middle_supported = previous is None or middle.value > previous.value
                right_supported = following is None or right.value < following.value
                if middle_supported and not right_supported:
                    popped.append(members.pop(index))
                elif right_supported and not middle_supported:
                    popped.append(members.pop(index + 1))
                else:
                    popped.append(members.pop(index))
            changed = True
            break
    return members, popped


def heal_run(
    run: PageNumberRun,
    all_candidates: Iterable[PageCandidate] = (),
    *,
    stronger_values: frozenset[int] | set[int] = frozenset(),
    page_break_lines: frozenset[int] | set[int] | None = None,
) -> tuple[PageNumberRun, tuple[InferredBoundary, ...], tuple[PageCandidate, ...]]:
    """Remove isolated detours, promote compatible observations, and infer gaps.

    ``stronger_values`` are page numbers already observed by higher-evidence
    runs of the same namespace; this run never infers them. ``page_break_lines``
    carries validated page-break anchor lines; when provided, a numeric gap is
    interpolated only if at least that many page breaks exist between the
    bracketing members (independent evidence that the pages exist). Without
    boundary information the historical bounded interpolation applies.
    """

    members, _popped = _repair_sequence(list(run.candidates))
    member_values = {candidate.value for candidate in members}
    member_ids = {(candidate.start_line, candidate.value) for candidate in members}
    changed = True
    while changed and len(members) >= 3:
        changed = False
        for index in range(1, len(members) - 1):
            if _is_detour(members[index - 1], members[index], members[index + 1]):
                members.pop(index)
                changed = True
                break

    candidates = [
        candidate
        for candidate in all_candidates
        if candidate.namespace == run.namespace
        and candidate.family == run.family
        and (candidate.start_line, candidate.value) not in member_ids
        and candidate.value not in member_values
    ]
    promoted: list[PageCandidate] = []
    for left, right in pairwise(members):
        between = [
            candidate
            for candidate in candidates
            if left.start_line < candidate.start_line < right.start_line
            and left.value < candidate.value < right.value
        ]
        if between and len(promoted) < max(1, len(members) // 2):
            promoted.append(
                min(between, key=lambda item: abs(item.value - left.value - 1))
            )
    if promoted:
        members = sorted({*members, *promoted}, key=lambda item: item.start_line)
        member_values.update(candidate.value for candidate in promoted)

    inferred: list[InferredBoundary] = []
    for left, right in pairwise(members):
        missing = right.value - left.value - 1
        if missing <= 0 or missing > MAX_INTERPOLATED_GAP:
            # Very large gaps are usually foreign values (years, totals)
            # inside the run rather than missing pages; interpolating them
            # floods metadata with phantom boundaries.
            continue
        breaks_between = None
        if page_break_lines is not None:
            breaks_between = sum(
                1
                for line in page_break_lines
                if left.start_line < line < right.start_line
            )
            if breaks_between < missing:
                # The numeric gap alone is not evidence that the pages exist.
                continue
        reason = "interpolated_gap"
        if breaks_between is not None:
            reason = (
                "validated_page_break_count"
                if breaks_between == missing
                else "page_break_supported"
            )
        for rank in range(1, missing + 1):
            value = left.value + rank
            if value in member_values or value in stronger_values:
                # Already observed here or by a higher-evidence run.
                continue
            inferred.append(
                InferredBoundary(
                    line=left.start_line
                    + (right.start_line - left.start_line) * rank / (missing + 1),
                    page_number=value,
                    namespace=run.namespace,
                    reason=reason,
                )
            )

    healed = validate_group(members, strategy=f"{run.strategy}:healed")
    if healed is None:
        healed = run
    return healed, tuple(inferred), tuple(promoted)


def unify_alternating_runs(
    runs: list[PageNumberRun],
) -> list[PageNumberRun]:
    """Unify complementary alternating (verso/recto step=2) runs into unified runs."""
    if len(runs) < 2:
        return runs

    merged_runs: list[PageNumberRun] = []
    used: set[int] = set()

    for i in range(len(runs)):
        if i in used:
            continue
        run_a = runs[i]
        for j in range(i + 1, len(runs)):
            if j in used:
                continue
            run_b = runs[j]
            if run_a.namespace != run_b.namespace:
                continue
            cand_a = list(run_a.candidates)
            cand_b = list(run_b.candidates)
            if len(cand_a) < 2 or len(cand_b) < 2:
                continue
            combined = sorted(cand_a + cand_b, key=lambda c: (c.start_line, c.start))
            values = [c.value for c in combined]
            if monotone_fraction(values, max_delta=2) >= 0.85:
                sources = [0 if c in cand_a else 1 for c in combined]
                alternations = sum(s1 != s2 for s1, s2 in pairwise(sources))
                if alternations / (len(sources) - 1) >= 0.6:
                    unified = validate_group(
                        combined,
                        strategy=f"alternating_verso_recto:{run_a.strategy}",
                        min_members=max(len(cand_a), len(cand_b)),
                        min_monotone=0.8,
                    )
                    if unified is not None:
                        merged_runs.append(unified)
                        used.add(i)
                        used.add(j)
                        break
        if i not in used:
            merged_runs.append(run_a)

    return merged_runs


__all__ = ["heal_run", "monotone_fraction", "unify_alternating_runs", "validate_group"]
