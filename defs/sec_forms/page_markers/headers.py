"""Conservative repeated ASCII header/footer classification."""

from __future__ import annotations

import re
from collections import defaultdict

from defs.regex import build_alternation
from defs.text import (
    CaseMode,
    EvidenceTier,
    LexicalEvidencePack,
    compile_evidence_pack,
    score_unit,
)
from defs.text.dates import MONTH_PATTERN, extract_years
from defs.text.logical_units import classify_units

from .layout import line_shape
from .models import (
    PageMarker,
    PageMarkerAction,
    PageMarkerDecision,
    PageMarkerKind,
    TemplateEvidence,
)

_PROSE_PACK = LexicalEvidencePack(
    name="page_marker_header_prose",
    tiers=(
        EvidenceTier(
            name="verbs",
            priority=2,
            value=2,
            terms=(
                "is",
                "are",
                "was",
                "were",
                "has",
                "have",
                "had",
                "will",
                "include",
                "provide",
                "contain",
            ),
            case_mode=CaseMode.LOWERCASE,
        ),
        EvidenceTier(
            name="currency_units",
            priority=1,
            value=1,
            terms=("usd", "million", "thousand"),
            support=True,
        ),
        EvidenceTier(
            name="per_share",
            priority=1,
            value=1,
            terms=("per share",),
            match_kind="ngram",
            support=True,
        ),
    ),
)
_COMPILED_PROSE = compile_evidence_pack(_PROSE_PACK)
_PAGE_TOKEN_RE = re.compile(r"\bpage\s+\d{1,4}\b", re.IGNORECASE)
_TRAILING_NUMBER_RE = re.compile(r"\s{2,}(?:\d{1,4}|[ivxlcdm]{1,8})\s*$", re.IGNORECASE)
_STRUCTURAL_WORDS = build_alternation(
    ["part", "item", "exhibit", "note"], auto_escape=True
)
_HEADER_HINTS = build_alternation(
    [
        "annual report",
        r"form \d",
        "financial",
        "consolidated",
        "continued",
        "corporation",
        "company",
    ],
    auto_escape=False,
)
_STRUCTURAL_RE = re.compile(rf"^\s*(?:{_STRUCTURAL_WORDS})\b", re.IGNORECASE)


def _clean_template(line: str) -> str:
    normalized = re.sub(r"\s+", " ", line.strip().casefold())
    normalized = _PAGE_TOKEN_RE.sub(" page #", normalized)
    normalized = _TRAILING_NUMBER_RE.sub(" #", normalized)
    return normalized.strip()


def _prose_warning(line: str) -> bool:
    stripped = line.strip()
    if len(stripped.split()) < 6:
        return False
    if stripped.endswith((",", ";", ":")):
        return True
    return score_unit(stripped, _COMPILED_PROSE).score >= 2


def _clean_date_heading(line: str) -> bool:
    years = extract_years(line)
    if len(years) != 1:
        return False
    lowered = line.casefold()
    if not re.search(MONTH_PATTERN, lowered):
        return False
    return bool(re.search(r"(?:\.|\d)\s*$", line))


def _eligible(
    line: str, toc_lines: set[int], line_index: int, unit_kind: str | None
) -> bool:
    stripped = line.strip()
    if not stripped or line_index in toc_lines or _STRUCTURAL_RE.match(stripped):
        return False
    if unit_kind == "table" or _prose_warning(line) or _clean_date_heading(line):
        return False
    shape = line_shape(line)
    if shape["all_caps"]:
        return True
    words = stripped.split()
    title_case = len(words) >= 2 and all(
        word[:1].isupper() for word in words if word[:1].isalpha()
    )
    hint = re.search(
        rf"(?i)\b(?:{_HEADER_HINTS})\b",
        stripped,
    )
    return bool(title_case or hint)


def analyze_repeating_headers(
    text: str,
    markers: list[PageMarker],
    *,
    toc_lines: set[int] | None = None,
) -> tuple[tuple[TemplateEvidence, ...], list[PageMarker], list[PageMarkerDecision]]:
    """Classify repeated text adjacent to accepted page anchors."""

    lines = text.splitlines()
    toc_lines = toc_lines or set()
    anchors = sorted(
        {marker.start_line for marker in markers if marker.start_line is not None}
    )
    if len(anchors) < 3:
        return (), [], []
    units_by_line: dict[int, str] = {}
    for unit in classify_units(text):
        for line_index in range(unit.start_line, unit.end_line + 1):
            units_by_line[line_index] = unit.kind
    groups: dict[tuple[str, int, str], list[tuple[int, str]]] = defaultdict(list)
    for anchor in anchors:
        for side, direction in (("header", 1), ("footer", -1)):
            index = anchor + direction
            while 0 <= index < len(lines) and not lines[index].strip():
                index += direction
            if not 0 <= index < len(lines):
                continue
            line = lines[index]
            if not _eligible(line, toc_lines, index, units_by_line.get(index)):
                continue
            groups[(side, abs(index - anchor) - 1, _clean_template(line))].append(
                (index, line)
            )

    templates: list[TemplateEvidence] = []
    header_markers: list[PageMarker] = []
    decisions: list[PageMarkerDecision] = []
    for (side, position, template), members in groups.items():
        if not template or len(members) < 3:
            continue
        presence = len(members) / len(anchors)
        if presence < 0.5:
            continue
        counts: dict[str, int] = {}
        for _, line in members:
            counts[_clean_template(line)] = counts.get(_clean_template(line), 0) + 1
        if max(counts.values()) / len(members) < 0.9 and len(members) < 8:
            continue
        kind = (
            PageMarkerKind.REPEATING_HEADER
            if side == "header"
            else PageMarkerKind.REPEATING_FOOTER
        )
        lines_seen = tuple(index for index, _ in members)
        templates.append(
            TemplateEvidence(
                side, position, template, len(members), presence, kind, lines_seen
            )
        )
        for index, raw in members:
            start = sum(len(value) + 1 for value in lines[:index])
            end = start + len(raw)
            marker = PageMarker(
                start=start,
                end=end,
                text=raw,
                kind=kind,
                representation="ascii",
                confidence=0.8,
                start_line=index,
                end_line=index,
                family=kind,
                evidence=("repeated_template", f"presence:{presence:.2f}"),
            )
            header_markers.append(marker)
            decisions.append(
                PageMarkerDecision(
                    marker,
                    PageMarkerAction.REMOVE,
                    "repeating_header_footer_template",
                    0.8,
                    marker.evidence,
                )
            )
    return tuple(templates), header_markers, decisions


__all__ = ["analyze_repeating_headers"]
