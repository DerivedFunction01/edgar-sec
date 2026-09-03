"""Namespace-aware sequence validation and conservative healing."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise
from statistics import median

from .models import InferredBoundary, PageCandidate, PageNumberRun


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


def heal_run(
    run: PageNumberRun,
    all_candidates: Iterable[PageCandidate] = (),
) -> tuple[PageNumberRun, tuple[InferredBoundary, ...], tuple[PageCandidate, ...]]:
    """Remove isolated detours, promote compatible observations, and infer gaps."""

    members = list(run.candidates)
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
        and candidate not in members
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

    inferred: list[InferredBoundary] = []
    for left, right in pairwise(members):
        missing = right.value - left.value - 1
        if missing <= 0:
            continue
        for rank in range(1, missing + 1):
            inferred.append(
                InferredBoundary(
                    line=left.start_line
                    + (right.start_line - left.start_line) * rank / (missing + 1),
                    page_number=left.value + rank,
                    namespace=run.namespace,
                    reason="interpolated_gap",
                )
            )

    healed = validate_group(members, strategy=f"{run.strategy}:healed")
    if healed is None:
        healed = run
    return healed, tuple(inferred), tuple(promoted)


__all__ = ["heal_run", "monotone_fraction", "validate_group"]
