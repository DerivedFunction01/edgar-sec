"""ASCII marker patterns, candidate extraction, and group promotion."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from defs.regex import build_alternation
from defs.text.patterns import PAGE_NUMBER_CORE

from .layout import candidate_template, cluster_is_table_like, has_numeric_data_shape
from .models import PageCandidate, PageMarker, PageMarkerKind, PageNumberRun
from .sequence import heal_run, validate_group

_RE_PAGE_NUMBER_OF_TOTAL = re.compile(
    r"(?im)^[ \t]*page[ \t]+(?P<page>\d+)[ \t]+of[ \t]+(?P<count>\d+)[ \t]*$"
)
_RE_NUMBER_OF_TOTAL = re.compile(
    r"(?im)^[ \t]*(?P<page>\d+)[ \t]+of[ \t]+(?P<count>\d+)[ \t]*$"
)
_RE_PAGE_NUMBER = re.compile(
    r"(?im)^[ \t]*page[ \t]+(?P<page>\d+)[ \t]*$", re.IGNORECASE
)
_RE_DASHED_NUMBER = re.compile(r"(?im)^[ \t]*-[ \t]*(?P<page>\d+)[ \t]*-[ \t]*$")
_RE_LETTER_NUMBER = re.compile(
    r"(?im)^\s*(?P<prefix>[A-Z])\s*[-–—]\s*(?P<page>\d+)\s*$"
)
_RE_SGML_LINE = re.compile(
    r"(?im)^[ \t]*</?PAGE\b[^>]*>[ \t]*(?P<page>\d+)?[ \t]*"
    r"(?:</?PAGE\b[^>]*>)?[ \t]*$"
)
_RE_SGML_INLINE = re.compile(r"(?i)</?PAGE\b[^>]*>")
_RE_BOUNDARY = re.compile(r"(?im)^[ \t]*(?:\(PAGE\)|\[PAGE\])[ \t]*$")
_WRAPPERS = build_alternation(["-", "–", "—", ".", "·", "•", "▪"], auto_escape=True)
_RE_DASH_LABEL = re.compile(
    rf"^(?=.*(?:{_WRAPPERS}))(?:{_WRAPPERS}|\s)+"
    rf"(?P<value>\d{{1,4}}|[ivxlcdm]{{1,8}})"
    rf"(?:{_WRAPPERS}|\s)+$",
    re.IGNORECASE,
)
_RE_PIPE_LABEL = re.compile(
    r"^\|\s*(?P<value>\d{1,4}|[ivxlcdm]{1,8})\s*\|$", re.IGNORECASE
)
_RE_PAREN_LABEL = re.compile(
    r"^\(\s*(?P<value>\d{1,4}|[ivxlcdm]{1,8})\s*\)$", re.IGNORECASE
)
_RE_SIMPLE_WRAPPED_LABEL = re.compile(
    r"^(?:[|]\s*\d{1,4}\s*[|]|\(\s*\d{1,4}\s*\)|\d{1,4}\.)$"
)
_RE_DOTTED_LABEL = re.compile(r"^(?P<value>\d{1,4})\.$")
_RE_BARE_ARABIC = re.compile(r"^(?P<value>\d{1,4})$")
_RE_BARE_ROMAN = re.compile(r"^(?P<value>[ivxlcdm]{1,8})$", re.IGNORECASE)
_RE_LEADING_NUMBER = re.compile(r"^(?P<value>\d{1,4})\s{1,}\S.*$")
_RE_TRAILING_NUMBER = re.compile(r"^\S.*?\s{2,}(?P<value>\d{1,4})$")
_RE_INLINE_PAGE = re.compile(
    r"^(?P<prefix>.{0,80}?\bpage\s+)(?P<value>\d{1,4})\b(?P<suffix>.{0,80})$",
    re.IGNORECASE,
)
_STRUCTURAL_WORDS = build_alternation(
    ["part", "item", "exhibit", "note"], auto_escape=True
)
_PAGE_MARKER_PATTERNS = (
    (PageMarkerKind.PAGE_NUMBER_OF_TOTAL, _RE_PAGE_NUMBER_OF_TOTAL),
    (PageMarkerKind.NUMBER_OF_TOTAL, _RE_NUMBER_OF_TOTAL),
    (PageMarkerKind.PAGE_NUMBER, _RE_PAGE_NUMBER),
    (PageMarkerKind.DASHED_NUMBER, _RE_DASHED_NUMBER),
    (PageMarkerKind.LETTER_NUMBER, _RE_LETTER_NUMBER),
    (PageMarkerKind.SGML, _RE_SGML_LINE),
    (PageMarkerKind.SGML, _RE_SGML_INLINE),
)
RE_PAGE_SUFFIX = re.compile(
    rf"(?:\b[A-Z])?[\.\-\s]?{PAGE_NUMBER_CORE}(?:\s*[\|+])?\s*$",
    re.IGNORECASE,
)


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
    remaining = total
    canonical = ""
    for numeral, amount in (
        ("m", 1000),
        ("cm", 900),
        ("d", 500),
        ("cd", 400),
        ("c", 100),
        ("xc", 90),
        ("l", 50),
        ("xl", 40),
        ("x", 10),
        ("ix", 9),
        ("v", 5),
        ("iv", 4),
        ("i", 1),
    ):
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
    import bisect

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
    text: str, representation: str, allow_letter_number: bool
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
    allow_letter_number: bool = False,
) -> PageCandidate | None:
    """Classify one short, structurally eligible ASCII line."""

    stripped = line.strip()
    if not stripped or stripped.casefold() in {"<page>", "</page>"}:
        return None
    if re.match(rf"(?i)^(?:{_STRUCTURAL_WORDS})\b", stripped):
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
        appendix = re.match(
            r"^(?P<prefix>[A-Za-z])-(?P<value>[ivxlcdm]{1,8})$",
            stripped,
            re.IGNORECASE,
        )
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
    allow_letter_number: bool = False,
    excluded_lines: set[int] | None = None,
) -> list[PageCandidate]:
    lines = text.splitlines()
    offsets = line_offsets(lines)
    excluded_lines = excluded_lines or set()
    candidates: list[PageCandidate] = []
    for index, line in enumerate(lines):
        if index in occupied_lines or index in excluded_lines or not line.strip():
            continue
        relatives: list[int | None] = [None]
        if anchors:
            relatives = []
            for anchor in anchors:
                if index == anchor:
                    continue
                direction = 1 if index > anchor else -1
                eligible = 0
                position = anchor + direction
                while position != index and 0 <= position < len(lines):
                    if (
                        lines[position].strip()
                        and position not in occupied_lines
                        and position not in excluded_lines
                    ):
                        eligible += 1
                    position += direction
                if 1 <= eligible + 1 <= 3:
                    relatives.append(direction * (eligible + 1))
            if not relatives:
                continue
            relatives.sort(key=lambda value: abs(value or 0))
        for relative in relatives:
            candidate = classify_candidate(
                line,
                index,
                offsets[index],
                relative=relative,
                allow_letter_number=allow_letter_number,
            )
            if candidate is not None:
                candidates.append(candidate)
                break
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
