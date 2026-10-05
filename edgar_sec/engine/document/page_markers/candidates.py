"""ASCII page-label extraction and admission.
A *firm* marker's line shape stands alone; every other shape is admitted only as a validated run of
same-shape, same-namespace candidates. Numeric, prose, and dense-cluster shapes are refused.
"""

from __future__ import annotations

import bisect
import re
from collections import defaultdict
from collections.abc import Callable
from itertools import pairwise
from statistics import median
from typing import Any, Protocol

from edgar_sec.engine.tables.currencies import ALL_CURRENCY_SYMBOLS
from edgar_sec.engine.tables.numeric_cells import is_numeric_cell
from edgar_sec.foundation.text.automaton import compile_lexical_matcher
from edgar_sec.foundation.text.tokens import ROMAN_NUMERAL_PATTERN, roman_to_int

from .models import (
    APPENDIX_ROMAN_LABEL,
    BARE_ARABIC,
    BARE_ROMAN,
    DASH_LABEL,
    DOTTED_LABEL,
    INLINE_PAGE_LABEL,
    LEADING_NUMBER_LABEL,
    LETTER_NUMBER_LABEL,
    PAGE_MARKER_PATTERNS,
    PAREN_LABEL,
    PIPE_HEADER_NUMBER_LABEL,
    PIPE_LABEL,
    PROSE_GUARD_STOP_WORDS,
    RE_BOUNDARY_TOKEN,
    RE_PAGE_VALUE,
    SIMPLE_WRAPPED_LABEL,
    STRUCTURAL_HEADING,
    TRAILING_NUMBER_LABEL,
    PageCandidate,
    PageMarker,
    PageMarkerKind,
    PageNumberRun,
)
from .sequence import (
    heal_run,
    monotone_fraction,
    unify_alternating_runs,
    validate_group,
)

_ASCII_PROBE_WINDOW = 2500

_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_NUMERIC_RE = re.compile(r"(?<![A-Za-z0-9])\d{1,4}(?![A-Za-z0-9])")
_DECIMAL_RE = re.compile(r"\d+\.\d{2,}")
_GROUPED_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
_PROSE_END_RE = re.compile(r"[,;:]$")

_COLLAPSE_WS_RE = re.compile(r"\s+")
_ROMAN_NUMERAL_RE = re.compile(
    rf"(?<![A-Za-z0-9]){ROMAN_NUMERAL_PATTERN}(?![A-Za-z0-9])"
)


class _TocSpan(Protocol):
    """The one field a contents span must state to be usable as an exclusion."""

    start_line: int
    end_line: int


_PROSE_WORDS = frozenset(
    {
        *PROSE_GUARD_STOP_WORDS,
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)
_MATCHER = compile_lexical_matcher({"page_marker_prose": sorted(_PROSE_WORDS)})


def prose_stop_words(text: str) -> frozenset[str]:
    """Return distinct grammar words found in a candidate text."""
    return frozenset(match.term.casefold() for match in _MATCHER.find_matches(text))


def looks_like_prose(text: str, *, minimum_hits: int = 3) -> bool:
    """Refuse a long candidate carrying several grammar words.
    Both must hold: a short title has function words, a long banner is one token.
    """
    words = text.split()
    return len(words) >= 6 and len(prose_stop_words(text)) >= minimum_hits


def candidate_template(text: str) -> str:
    """Mask page values so two labels differing only in number are one template.
    Roman is masked too, or an appendix notation change splits the run in two.
    """

    normalized = _COLLAPSE_WS_RE.sub(" ", text.strip().casefold())
    normalized = _NUMERIC_RE.sub("#", normalized)
    return _ROMAN_NUMERAL_RE.sub("#", normalized)


def has_numeric_data_shape(line: str) -> bool:
    """Refuse a financial-looking line from page-label promotion.
    Currency or percent, a decimal or grouped figure, two bare numbers split by a gutter, or a whole-cell numeric match.
    """

    stripped = line.strip()
    if not stripped:
        return False
    if any(symbol in stripped for symbol in ALL_CURRENCY_SYMBOLS) or "%" in stripped:
        return True
    if _DECIMAL_RE.search(stripped) or _GROUPED_RE.search(stripped):
        return True
    numbers = _NUMERIC_RE.findall(stripped)
    if len(numbers) >= 2 and len(_MULTI_SPACE_RE.findall(line)) >= 1:
        return True
    return is_numeric_cell(stripped) and len(stripped) > 4


def cluster_is_table_like(candidates: list[PageCandidate]) -> bool:
    """Return whether candidate spacing reads as a dense table burst.
    Inline-``page N`` is exempt: a running "continued on page N" header clusters tightly by nature.
    """

    if len(candidates) < 3:
        return False
    if all(
        candidate.family == PageMarkerKind.INLINE_PAGE_NUMBER
        and "page" in candidate.text.casefold()
        for candidate in candidates
    ):
        return False
    ordered = sorted(candidates, key=lambda item: item.start_line)
    gaps = [right.start_line - left.start_line for left, right in pairwise(ordered)]
    if not gaps:
        return False
    gap_mean = sum(gaps) / len(gaps)
    gap_median = median(gaps)
    dense = sum(gap <= 3 for gap in gaps) / len(gaps)
    return gap_mean < 8 or dense >= 0.15 or gap_mean / gap_median < 0.5


def line_offsets(lines: list[str]) -> list[int]:
    """Return the character offset at which each line starts."""
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1
    return offsets


def line_for_offset(offsets: list[int], offset: int) -> int:
    """Return the index of the line containing ``offset``."""
    return max(0, min(bisect.bisect_right(offsets, offset) - 1, len(offsets) - 1))


def _marker_lines(
    start: int, end: int, text: str, offsets: list[int]
) -> tuple[int, int]:
    value = text[start:end]
    first = start + len(value) - len(value.lstrip())
    return line_for_offset(offsets, first), line_for_offset(
        offsets, max(first, end - 1)
    )


def firm_markers(
    text: str, representation: str, allow_letter_number: bool = True
) -> tuple[list[PageMarker], set[tuple[int, int]], set[int]]:
    """Find exact marker spans and the lines they occupy.
    Spans are claimed in pattern order; an occupied line cannot also yield a candidate.
    """

    offsets = line_offsets(text.splitlines())
    occupied_starts: list[int] = []
    occupied_ends: list[int] = []
    markers: list[PageMarker] = []

    def _is_occupied(s: int, e: int) -> bool:
        idx = bisect.bisect_right(occupied_starts, s)
        if idx > 0 and occupied_ends[idx - 1] > s:
            return True
        return idx < len(occupied_starts) and occupied_starts[idx] < e

    def _add_occupied(s: int, e: int) -> None:
        idx = bisect.bisect_right(occupied_starts, s)
        occupied_starts.insert(idx, s)
        occupied_ends.insert(idx, e)

    for kind, pattern in PAGE_MARKER_PATTERNS:
        if kind == PageMarkerKind.LETTER_NUMBER and not allow_letter_number:
            continue
        for match in pattern.finditer(text):
            start, end = match.span()
            if _is_occupied(start, end):
                continue
            _add_occupied(start, end)
            groups = match.groupdict()
            start_line, end_line = _marker_lines(start, end, text, offsets)
            page = groups.get("page")
            count = groups.get("count")
            markers.append(
                PageMarker(
                    start=start,
                    end=end,
                    text=match.group(0),
                    kind=kind,
                    page_number=int(page) if page and page.isdigit() else None,
                    page_count=int(count) if count and count.isdigit() else None,
                    representation=representation,
                    confidence=0.7 if kind == PageMarkerKind.LETTER_NUMBER else 0.95,
                    start_line=start_line,
                    end_line=end_line,
                    namespace=(groups.get("prefix") or "").upper() or "arabic",
                    family=kind,
                    evidence=("firm_pattern",),
                )
            )
    for match in RE_BOUNDARY_TOKEN.finditer(text):
        start, end = match.span()
        if _is_occupied(start, end):
            continue
        start_line, end_line = _marker_lines(start, end, text, offsets)
        _add_occupied(start, end)
        markers.append(
            PageMarker(
                start=start,
                end=end,
                text=match.group(0),
                kind=PageMarkerKind.BOUNDARY,
                representation=representation,
                confidence=0.9,
                start_line=start_line,
                end_line=end_line,
                family=PageMarkerKind.BOUNDARY,
                evidence=("boundary_only",),
            )
        )
    markers.sort(key=lambda marker: marker.start)
    lines: set[int] = set()
    for marker in markers:
        lines.update(range(marker.start_line or 0, (marker.end_line or 0) + 1))
    return markers, set(zip(occupied_starts, occupied_ends)), lines


def _candidate(
    match: re.Match[str],
    line: str,
    index: int,
    start: int,
    family: str,
    value_text: str,
    namespace: str,
    relative: int | None,
    whole_line: bool,
) -> PageCandidate | None:
    value = int(value_text) if value_text.isdigit() else roman_to_int(value_text)
    if value is None or value <= 0:
        return None
    leading = len(line) - len(line.lstrip())
    if whole_line:
        left = start + leading
        right = start + len(line.rstrip())
        text = line[leading:].rstrip()
    elif family == PageMarkerKind.INLINE_PAGE_NUMBER:
        left = start + match.start("prefix")
        right = start + match.end("value")
        text = line[match.start("prefix") : match.end("value")]
    else:
        left = start + match.start("value")
        right = start + match.end("value")
        text = line[match.start() : match.end()]
    return PageCandidate(
        left,
        right,
        index,
        index,
        text,
        family,
        namespace,
        value,
        relative,
        leading,
        candidate_template(line),
    )


def classify_candidate(
    line: str,
    index: int,
    start: int,
    *,
    relative: int | None = None,
    allow_letter_number: bool = True,
) -> PageCandidate | None:
    """Classify one short, eligible ASCII line; the most specific shape wins.
    Refused before any shape is tried: blank, bare ``<PAGE>``, a ``PART``/``ITEM``/``NOTE`` heading, or a numeric data shape.
    """

    stripped = line.strip()
    if not stripped or stripped.casefold() in {"<page>", "</page>"}:
        return None
    if STRUCTURAL_HEADING.match(stripped):
        return None
    if has_numeric_data_shape(line) and not (
        RE_PAGE_VALUE.fullmatch(stripped)
        or SIMPLE_WRAPPED_LABEL.fullmatch(stripped)
        or PIPE_HEADER_NUMBER_LABEL.match(stripped)
    ):
        return None
    checks: tuple[tuple[re.Pattern[str], str, str, bool], ...] = (
        (DASH_LABEL, PageMarkerKind.DASHED_NUMBER, "arabic", True),
        (PIPE_LABEL, PageMarkerKind.PIPE_NUMBER, "arabic", True),
        (PAREN_LABEL, PageMarkerKind.PAREN_NUMBER, "arabic", True),
        (DOTTED_LABEL, PageMarkerKind.DOTTED_NUMBER, "arabic", True),
        (BARE_ARABIC, PageMarkerKind.BARE_NUMBER, "arabic", True),
        (BARE_ROMAN, PageMarkerKind.ROMAN_NUMBER, "roman", True),
        (LEADING_NUMBER_LABEL, PageMarkerKind.NUMBER_FIRST, "arabic", False),
        (TRAILING_NUMBER_LABEL, PageMarkerKind.TRAILING_NUMBER, "arabic", False),
        (PIPE_HEADER_NUMBER_LABEL, PageMarkerKind.TRAILING_NUMBER, "arabic", False),
        (INLINE_PAGE_LABEL, PageMarkerKind.INLINE_PAGE_NUMBER, "arabic", False),
    )
    for pattern, family, namespace, whole_line in checks:
        match = pattern.match(stripped)
        if match is None:
            continue
        if family in {
            PageMarkerKind.NUMBER_FIRST,
            PageMarkerKind.TRAILING_NUMBER,
            PageMarkerKind.INLINE_PAGE_NUMBER,
        } and (len(stripped.split()) > 12 or len(stripped) > 120):
            continue
        if family == PageMarkerKind.DASHED_NUMBER:
            namespace = "arabic" if match.group("value").isdigit() else "roman"
        return _candidate(
            match,
            stripped,
            index,
            start + len(line) - len(line.lstrip()),
            family,
            match.group("value"),
            namespace,
            relative,
            whole_line,
        )
    if allow_letter_number:
        match = LETTER_NUMBER_LABEL.match(stripped)
        if match:
            return _candidate(
                match,
                stripped,
                index,
                start + len(line) - len(line.lstrip()),
                PageMarkerKind.LETTER_NUMBER,
                match.group("page"),
                match.group("prefix").upper(),
                relative,
                True,
            )
        appendix = APPENDIX_ROMAN_LABEL.match(stripped)
        if appendix and roman_to_int(appendix.group("value")) is not None:
            return _candidate(
                appendix,
                stripped,
                index,
                start + len(line) - len(line.lstrip()),
                PageMarkerKind.APPENDIX_ROMAN,
                appendix.group("value"),
                appendix.group("prefix").upper(),
                relative,
                True,
            )
    return None


def toc_lines(
    text: str, span_finder: Callable[[str], _TocSpan | None] | None = None
) -> set[int]:
    """Return the source line indices a contents span excludes (``start`` inclusive, ``end`` exclusive).
    The span comes from the caller's resolver, never from here: that dependency runs one way.
    """
    if span_finder is None:
        from edgar_sec.engine.forms.cover.toc.finder import find_toc_span

        span_finder = find_toc_span
    span = span_finder(text)
    return set(range(span.start_line, span.end_line)) if span is not None else set()


def all_candidates(
    text: str,
    occupied_lines: set[int],
    *,
    anchors: set[int] | None = None,
    allow_letter_number: bool = True,
    excluded_lines: set[int] | None = None,
) -> list[PageCandidate]:
    """Collect candidate labels around anchors, or across the document.
    With anchors, only the three nearest eligible lines each side are evidence about that boundary.
    """

    lines = text.splitlines()
    offsets = line_offsets(lines)
    excluded_lines = excluded_lines or set()
    candidates: list[PageCandidate] = []
    memo: dict[int, PageCandidate | None] = {}

    def _get_candidate(idx: int, relative: int | None = None) -> PageCandidate | None:
        if idx in memo:
            return memo[idx]
        if idx in occupied_lines or idx in excluded_lines:
            memo[idx] = None
            return None
        line = lines[idx]
        if not line.strip() or len(line) > 120:
            memo[idx] = None
            return None
        cand = classify_candidate(
            line,
            idx,
            offsets[idx],
            relative=relative,
            allow_letter_number=allow_letter_number,
        )
        memo[idx] = cand
        return cand

    if anchors:
        relatives_by_line: dict[int, list[int]] = {}
        scan_anchors = [(a, d) for a in anchors for d in (1, -1)]
        if len(anchors) >= 2:
            scan_anchors.extend([(-1, 1), (len(lines), -1)])
        for anchor, direction in scan_anchors:
            eligible = 0
            pos = anchor + direction
            while 0 <= pos < len(lines) and eligible < 3:
                if (
                    lines[pos].strip()
                    and pos not in occupied_lines
                    and pos not in excluded_lines
                ):
                    eligible += 1
                    relatives_by_line.setdefault(pos, []).append(direction * eligible)
                pos += direction

        for index in sorted(relatives_by_line.keys()):
            relatives = relatives_by_line[index]
            relatives.sort(key=lambda value: abs(value or 0))
            for relative in relatives:
                candidate = _get_candidate(index, relative=relative)
                if candidate is not None:
                    candidates.append(candidate)
                    break
    else:
        n_lines = len(lines)
        if n_lines <= 250:
            for idx in range(n_lines):
                candidate = _get_candidate(idx)
                if candidate is not None:
                    candidates.append(candidate)
        else:
            probe_lines = min(n_lines // 4, _ASCII_PROBE_WINDOW)
            front_limit = probe_lines
            tail_start = n_lines - probe_lines
            front_cands: list[PageCandidate] = []
            for idx in range(front_limit):
                c = _get_candidate(idx)
                if c is not None:
                    front_cands.append(c)
            for idx in range(tail_start, n_lines):
                _get_candidate(idx)

            if len(front_cands) >= 3:
                vals = [c.value for c in front_cands if c.namespace == "arabic"]
                if len(vals) >= 3 and vals[-1] > vals[0]:
                    stride = (
                        front_cands[-1].start_line - front_cands[0].start_line
                    ) // (vals[-1] - vals[0])
                    if stride >= 10:
                        curr = front_cands[-1].start_line + stride
                        while curr < tail_start:
                            for offset_line in range(
                                max(0, curr - 4), min(n_lines, curr + 5)
                            ):
                                _get_candidate(offset_line)
                            curr += stride

            for idx in range(n_lines):
                candidate = _get_candidate(idx)
                if candidate is not None:
                    candidates.append(candidate)

    return candidates


def marker_for_candidate(
    candidate: PageCandidate, confidence: float, evidence: tuple[str, ...]
) -> PageMarker:
    """Promote one admitted candidate to a marker carrying its run evidence."""
    return PageMarker(
        candidate.start,
        candidate.end,
        candidate.text,
        candidate.family,
        candidate.value,
        representation="ascii",
        confidence=confidence,
        start_line=candidate.start_line,
        end_line=candidate.end_line,
        namespace=candidate.namespace,
        family=candidate.family,
        evidence=evidence,
    )


def promote_groups(
    candidates: list[PageCandidate],
    *,
    anchored: bool,
) -> tuple[list[PageMarker], list[PageNumberRun], list[PageCandidate], tuple[str, ...]]:
    """Group candidates by slot and admit the groups that form a validated run.
    Anchorless groups face stricter spacing: with no anchor a dense cluster of same-shaped numbers is far likelier a table. Rejections stay named diagnostics.
    """

    groups: dict[tuple[Any, ...], list[PageCandidate]] = defaultdict(list)
    for candidate in candidates:
        if anchored:
            key = (candidate.relative_position, candidate.family, candidate.namespace)
        else:
            key = (
                candidate.family,
                candidate.namespace,
                candidate.leading_column // 2,
                candidate.template,
            )
        groups[key].append(candidate)
    markers: list[PageMarker] = []
    runs: list[PageNumberRun] = []
    accepted: list[PageCandidate] = []
    rejections: list[str] = []
    for members in groups.values():
        if not anchored and cluster_is_table_like(members):
            rejections.append("table_like_cluster")
            continue
        run = validate_group(
            members,
            strategy="anchor_relative" if anchored else "anchorless",
            min_gap_median=0 if anchored else 8,
        )
        if run is None:
            if len(members) < 3:
                rejections.append("fewer_than_min_members")
            else:
                mono = monotone_fraction(item.value for item in members)
                if mono < 0.8:
                    rejections.append("monotonicity_failure")
                else:
                    rejections.append("gap_median_failure")
            provisional = validate_group(
                members,
                strategy="anchor_relative" if anchored else "anchorless",
                min_monotone=0.0,
                min_gap_median=0 if anchored else 8,
            )
            if provisional is None:
                rejections.append("provisional_validation_failed")
                continue
            healed, _inferred, _promoted = heal_run(provisional, members)
            if healed.monotone_fraction < 0.8:
                rejections.append("healed_monotone_below_threshold")
                continue
            run = provisional
        if run is None or (
            not anchored and run.alignment_fraction < 0.6 and len(members) < 10
        ):
            if not anchored and run is not None:
                rejections.append("alignment_fraction_below_threshold")
            continue
        healed, _inferred, promoted = heal_run(run, members)
        runs.append(healed)
        accepted.extend(healed.candidates)
        evidence = (
            "anchor_relative_sequence" if anchored else "anchorless_sequence",
            f"monotone:{healed.monotone_fraction:.2f}",
        )
        if promoted:
            evidence += (f"promoted:{len(promoted)}",)
        markers.extend(
            marker_for_candidate(candidate, 0.88 if anchored else 0.8, evidence)
            for candidate in healed.candidates
        )
        if anchored:
            accepted_lines = {c.start_line for c in healed.candidates}
            accepted_values = {c.value for c in healed.candidates}
            dup_evidence = (
                "anchor_relative_sequence",
                "anchored_duplicate_page",
                f"monotone:{healed.monotone_fraction:.2f}",
            )
            for candidate in members:
                if (
                    candidate.start_line not in accepted_lines
                    and candidate.value in accepted_values
                ):
                    accepted_lines.add(candidate.start_line)
                    accepted.append(candidate)
                    markers.append(marker_for_candidate(candidate, 0.88, dup_evidence))
    runs = unify_alternating_runs(runs)
    return markers, runs, accepted, tuple(rejections)


__all__ = [
    "all_candidates",
    "candidate_template",
    "classify_candidate",
    "cluster_is_table_like",
    "firm_markers",
    "has_numeric_data_shape",
    "line_for_offset",
    "line_offsets",
    "looks_like_prose",
    "marker_for_candidate",
    "promote_groups",
    "prose_stop_words",
    "toc_lines",
]
