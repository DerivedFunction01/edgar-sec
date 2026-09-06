"""ASCII marker patterns, candidate extraction, and group promotion."""

from __future__ import annotations

import bisect
import re
from collections import defaultdict
from typing import Any

from .constants import (
    _NUMERALS,
    _PAGE_MARKER_PATTERNS,
    _RE_APPENDIX_ROMAN,
    _RE_BARE_ARABIC,
    _RE_BARE_ROMAN,
    _RE_BOUNDARY,
    _RE_DASH_LABEL,
    _RE_DOTTED_LABEL,
    _RE_INLINE_PAGE,
    _RE_LEADING_NUMBER,
    _RE_LETTER_NUMBER,
    _RE_PAREN_LABEL,
    _RE_PIPE_LABEL,
    _RE_SIMPLE_WRAPPED_LABEL,
    _RE_STRUCTURAL_MATCH,
    _RE_TRAILING_NUMBER,
    RE_PAGE_SUFFIX,
)
from .layout import candidate_template, cluster_is_table_like, has_numeric_data_shape

_ASCII_PROBE_WINDOW = 2500
from .models import PageCandidate, PageMarker, PageMarkerKind, PageNumberRun
from .sequence import heal_run, unify_alternating_runs, validate_group


def roman_to_int(value: str) -> int | None:
    """Parse a canonical bounded Roman numeral."""
    text = value.casefold()
    if not re.fullmatch(r"[ivxlcdm]{1,8}", text):
        return None
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = previous = 0
    for char in reversed(text):
        current = values[char]
        total += -current if current < previous else current
        previous = max(previous, current)
    if not 0 < total <= 3000:
        return None
    remaining, canonical = total, ""
    for numeral, amount in _NUMERALS:
        count, remaining = divmod(remaining, amount)
        canonical += numeral * count
    return total if canonical == text else None


def line_offsets(lines: list[str]) -> list[int]:
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1
    return offsets


def line_for_offset(offsets: list[int], offset: int) -> int:
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
    """Find exact marker spans and their line occupancy."""

    offsets = line_offsets(text.splitlines())
    occupied: list[tuple[int, int]] = []
    markers: list[PageMarker] = []
    for kind, pattern in _PAGE_MARKER_PATTERNS:
        if kind == PageMarkerKind.LETTER_NUMBER and not allow_letter_number:
            continue
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < right and left < end for left, right in occupied):
                continue
            occupied.append((start, end))
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
    for match in _RE_BOUNDARY.finditer(text):
        start, end = match.span()
        if any(start < right and left < end for left, right in occupied):
            continue
        start_line, end_line = _marker_lines(start, end, text, offsets)
        occupied.append((start, end))
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
    return markers, set(occupied), lines


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
    """Classify one short, structurally eligible ASCII line."""

    stripped = line.strip()
    if not stripped or stripped.casefold() in {"<page>", "</page>"}:
        return None
    if _RE_STRUCTURAL_MATCH.match(stripped):
        return None
    if has_numeric_data_shape(line) and not (
        re.fullmatch(r"(?:\d{1,4}|[ivxlcdm]{1,8})", stripped, re.IGNORECASE)
        or _RE_SIMPLE_WRAPPED_LABEL.fullmatch(stripped)
    ):
        return None
    checks: tuple[tuple[re.Pattern[str], str, str, bool], ...] = (
        (_RE_DASH_LABEL, PageMarkerKind.DASHED_NUMBER, "arabic", True),
        (_RE_PIPE_LABEL, PageMarkerKind.PIPE_NUMBER, "arabic", True),
        (_RE_PAREN_LABEL, PageMarkerKind.PAREN_NUMBER, "arabic", True),
        (_RE_DOTTED_LABEL, PageMarkerKind.DOTTED_NUMBER, "arabic", True),
        (_RE_BARE_ARABIC, PageMarkerKind.BARE_NUMBER, "arabic", True),
        (_RE_BARE_ROMAN, PageMarkerKind.ROMAN_NUMBER, "roman", True),
        (_RE_LEADING_NUMBER, PageMarkerKind.NUMBER_FIRST, "arabic", False),
        (_RE_TRAILING_NUMBER, PageMarkerKind.TRAILING_NUMBER, "arabic", False),
        (_RE_INLINE_PAGE, PageMarkerKind.INLINE_PAGE_NUMBER, "arabic", False),
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
        match = _RE_LETTER_NUMBER.match(stripped)
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
        appendix = _RE_APPENDIX_ROMAN.match(stripped)
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


def toc_lines(text: str) -> set[int]:
    """Resolve TOC exclusions lazily to avoid the cover import cycle."""

    try:
        from defs.sec_forms.cover.toc import find_toc_span

        span = find_toc_span(text)
    except (ImportError, RecursionError):
        span = None
    return set(range(span.start_line, span.end_line)) if span is not None else set()


def all_candidates(
    text: str,
    occupied_lines: set[int],
    *,
    anchors: set[int] | None = None,
    allow_letter_number: bool = True,
    excluded_lines: set[int] | None = None,
) -> list[PageCandidate]:
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
        for anchor in anchors:
            for direction in (1, -1):
                eligible = 0
                pos = anchor + direction
                while 0 <= pos < len(lines) and eligible < 3:
                    if (
                        lines[pos].strip()
                        and pos not in occupied_lines
                        and pos not in excluded_lines
                    ):
                        eligible += 1
                        relatives_by_line.setdefault(pos, []).append(
                            direction * eligible
                        )
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
            # Progressive bidirectional scan: bounded front/tail windows.
            # Large documents do not need half the document probed to find a
            # repeated pattern; windows cap at _ASCII_PROBE_WINDOW lines.
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

            # Adaptive stride hopping if front probe found a sequence
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

            # Sweep remaining unvisited lines via memo cache
            for idx in range(n_lines):
                candidate = _get_candidate(idx)
                if candidate is not None:
                    candidates.append(candidate)

    return candidates


def marker_for_candidate(
    candidate: PageCandidate, confidence: float, evidence: tuple[str, ...]
) -> PageMarker:
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
) -> tuple[list[PageMarker], list[PageNumberRun], list[PageCandidate]]:
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
    for members in groups.values():
        if not anchored and cluster_is_table_like(members):
            continue
        run = validate_group(
            members,
            strategy="anchor_relative" if anchored else "anchorless",
            min_gap_median=0 if anchored else 8,
        )
        if run is None:
            # Healing needs a provisional run so an isolated outlier such as
            # 10, 47, 11 can be removed before the strict monotone gate.
            provisional = validate_group(
                members,
                strategy="anchor_relative" if anchored else "anchorless",
                min_monotone=0.0,
                min_gap_median=0 if anchored else 8,
            )
            if provisional is None:
                continue
            healed, _inferred, _promoted = heal_run(provisional, members)
            if healed.monotone_fraction < 0.8:
                continue
            run = provisional
        if run is None or (
            not anchored and run.alignment_fraction < 0.6 and len(members) < 10
        ):
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
    runs = unify_alternating_runs(runs)
    return markers, runs, accepted


__all__ = [
    "RE_PAGE_SUFFIX",
    "_PAGE_MARKER_PATTERNS",
    "_RE_BOUNDARY",
    "all_candidates",
    "classify_candidate",
    "firm_markers",
    "line_for_offset",
    "line_offsets",
    "marker_for_candidate",
    "promote_groups",
    "roman_to_int",
    "toc_lines",
]
