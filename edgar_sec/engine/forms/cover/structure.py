"""Generic structural matching for cover, TOC, and body boundaries.

Owns only representation-neutral PART/ITEM heading mechanics. TOC-specific
patterns live in :mod:`edgar_sec.engine.tables.toc` to keep this module generic
and free of annual-report-specific phrasing.

The distinction that matters throughout the boundary detector is
``is_exact_heading``: an isolated ``ITEM 1. Business`` heading is a structural
anchor, while ``as noted in Item 1`` is prose that merely mentions a section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.tokens import BULLET_MARKER_RE, BULLET_MARKERS

_HEADING_SEPARATOR_CHARS = ":.- |+\t" + "".join(BULLET_MARKERS)


class SectionKind(StrEnum):
    """Canonical structural role for an SEC filing section."""

    PART = "part"
    ITEM = "item"


class StructuralRole:
    """Stable names for generic structural match roles."""

    PART = "part"
    ITEM = "item"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ParsedSection:
    """A parsed structural section heading or reference."""

    kind: SectionKind
    identifier: str
    canonical_label: str
    title: str = ""
    is_exact_heading: bool = True


@dataclass(frozen=True, slots=True)
class StructuralMatch:
    """A single structural heading match with role and continuation info."""

    line: int
    role: str
    label: str
    is_exact_heading: bool
    reference_count: int
    continuation_text: str = ""


# Roman numeral alternation for generic PART matching.
_ROMAN_PARTS = ("IV", "III", "II", "I", "V")
_ROMAN_PARTS_ALTERNATION = build_alternation(list(_ROMAN_PARTS), auto_escape=True)

# Exact PART heading: isolated after trimming, optional period, optional
# "(Continued)" marker. Prose such as "Part III. hereof." never matches.
RE_PART = re.compile(
    rf"^\s*PART\s+{_ROMAN_PARTS_ALTERNATION}\s*\.?\s*(?:\(\s*continued\s*\))?\s*$",
    re.IGNORECASE,
)

RE_PART_ONE = re.compile(
    r"^\s*PART\s+I\s*\.?\s*(?:\(\s*continued\s*\))?\s*$", re.IGNORECASE
)

# Real ITEM headings (1, 1A, 1.01, 5.02, 9.01, etc.) carry a title-case title
# after an optional separator. TOC rows ("ITEM 1. BUSINESS ..... 1") fail
# because the title may contain dot leaders or a trailing page number.
RE_ITEM_EXACT = re.compile(
    r"^\s*ITEMS?\s+(?:\d+[A-Z]?(?:\.\d{1,2})?)\b\s*(?:[.:;\-]+\s*)?"
    r"(?:(?-i:[A-Z])[A-Za-z0-9,&'()\s-]*)?[:.]?\s*"
    r"(?:\(\s*continued\s*\))?\s*$",
    re.IGNORECASE,
)
RE_ITEM_ONE = re.compile(
    r"^\s*ITEM\s+1\b\s*(?:[.:;\-]+\s*)?"
    r"(?:(?-i:[A-Z])[A-Za-z,&'()\s-]*)?[:.]?\s*"
    r"(?:\(\s*continued\s*\))?\s*$",
    re.IGNORECASE,
)
RE_ITEM_ONE_A = re.compile(
    r"^\s*ITEM\s+1A\b\s*(?:[.:;\-]+\s*)?"
    r"(?:(?-i:[A-Z])[A-Za-z,&'()\s-]*)?[:.]?\s*"
    r"(?:\(\s*continued\s*\))?\s*$",
    re.IGNORECASE,
)

# Generic SEC structural references. These intentionally do not enumerate
# form-family taxonomies: future forms may add PART labels or decimal ITEM
# labels without changing this module.
RE_PART_REFERENCE = re.compile(r"\bPART\s+(?:[IVXLCDM]+|\d+)\b", re.IGNORECASE)
RE_ITEM_REFERENCE = re.compile(r"\bITEM\s+\d+(?:\.\d+)*[A-Z]?\b", re.IGNORECASE)

# Anchored section headings for exact structure matching. Requires line-leading
# structural tokens; disallows leading prose or filler words.
_PART_HEADING_RE = re.compile(
    r"^\s*(?:[\|+•\t-]\s*)?PART\s+([IVXLCDM]+|\d+)\b(?:\s*[:.\-]\s*|\s+)?(?:\(\s*continued\s*\))?(.*)$",
    re.IGNORECASE,
)
_ITEM_HEADING_RE = re.compile(
    r"^\s*(?:[\|+•\t-]\s*)?ITEMS?\s+(\d+[A-Z]?(?:\.\d{1,2})?)\b(?:\s*[:.\-]\s*|\s+)?(?:\(\s*continued\s*\))?(.*)$",
    re.IGNORECASE,
)
_PART_INLINE_RE = re.compile(r"\bPART\s+([IVXLCDM]+|\d+)\b", re.IGNORECASE)
_ITEM_INLINE_RE = re.compile(r"\bITEMS?\s+(\d+[A-Z]?(?:\.\d{1,2})?)\b", re.IGNORECASE)
_SECTION_REFERENCE_RE = re.compile(
    r"\b(?:PART|ITEM)\s+(?:[IVX]+|[0-9]+[A-Z]?)\b\s*(.*)", re.IGNORECASE
)

_CONTINUATION_WORDS = (
    "including",
    "includes",
    "include",
    "from",
    "into",
    "under",
    "of",
    "to",
)
_CONTINUATION_WORDS_ALT = build_alternation(list(_CONTINUATION_WORDS), auto_escape=True)
RE_PRECEDING_CONTINUATION = re.compile(
    rf"(?:\b{_CONTINUATION_WORDS_ALT}\s*:?|:)\s*$", re.IGNORECASE
)


def _extract_continuation(stripped: str) -> str:
    """Extract the text following a section reference token."""
    match = _SECTION_REFERENCE_RE.search(stripped)
    if match:
        return match.group(1).strip()
    return ""


def match_structural_line(line: str, line_number: int) -> StructuralMatch | None:
    """Classify one line as a generic structural heading candidate.

    Returns ``None`` when the line is not a structural candidate, and a match
    with ``is_exact_heading=False`` when the line merely contains a section
    reference inside prose.
    """
    stripped = line.strip()
    if not stripped:
        return None

    part_refs = len(RE_PART_REFERENCE.findall(stripped))
    item_refs = len(RE_ITEM_REFERENCE.findall(stripped))
    reference_count = part_refs + item_refs

    if RE_PART.match(stripped):
        return StructuralMatch(
            line=line_number,
            role=StructuralRole.PART,
            label=stripped,
            is_exact_heading=True,
            reference_count=part_refs,
        )

    if RE_ITEM_EXACT.match(stripped):
        return StructuralMatch(
            line=line_number,
            role=StructuralRole.ITEM,
            label=stripped,
            is_exact_heading=True,
            reference_count=max(item_refs, 1),
        )

    if reference_count > 0:
        return StructuralMatch(
            line=line_number,
            role=StructuralRole.UNKNOWN,
            label=stripped,
            is_exact_heading=False,
            reference_count=reference_count,
            continuation_text=_extract_continuation(stripped),
        )

    return None


def parse_section_heading(
    text: str, *, allow_inline: bool = False
) -> ParsedSection | None:
    """Parse a structural Part or Item heading.

    By default requires line-leading structural tokens, so leading prose or
    filler words return ``None``. With ``allow_inline=True`` a prose mention is
    recognized and flagged ``is_exact_heading=False``.
    """
    if not text:
        return None
    stripped = text.strip()

    part_match = _PART_HEADING_RE.match(stripped)
    if part_match:
        part_num = part_match.group(1).upper()
        title = part_match.group(2).strip().strip(_HEADING_SEPARATOR_CHARS)
        return ParsedSection(
            kind=SectionKind.PART,
            identifier=part_num,
            canonical_label=f"PART {part_num}",
            title=title,
            is_exact_heading=True,
        )

    item_match = _ITEM_HEADING_RE.match(stripped)
    if item_match:
        item_num = item_match.group(1).upper()
        title = item_match.group(2).strip().strip(_HEADING_SEPARATOR_CHARS)
        return ParsedSection(
            kind=SectionKind.ITEM,
            identifier=item_num,
            canonical_label=f"ITEM {item_num}",
            title=title,
            is_exact_heading=True,
        )

    if allow_inline:
        part_ref = _PART_INLINE_RE.search(stripped)
        if part_ref:
            part_num = part_ref.group(1).upper()
            return ParsedSection(
                kind=SectionKind.PART,
                identifier=part_num,
                canonical_label=f"PART {part_num}",
                is_exact_heading=False,
            )
        item_ref = _ITEM_INLINE_RE.search(stripped)
        if item_ref:
            item_num = item_ref.group(1).upper()
            return ParsedSection(
                kind=SectionKind.ITEM,
                identifier=item_num,
                canonical_label=f"ITEM {item_num}",
                is_exact_heading=False,
            )

    return None


def is_exact_heading(line: str) -> bool:
    """Return whether ``line`` is an isolated PART/ITEM structural heading."""
    stripped = line.strip()
    if not stripped:
        return False
    return bool(RE_PART.match(stripped) or RE_ITEM_EXACT.match(stripped))


def is_continuation_prose(line: str) -> bool:
    """Return whether ``line`` continues a previous sentence.

    Rejects PART/ITEM references embedded in prose such as ``Part III. hereof.``
    or bulleted reference lists.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if is_exact_heading(stripped):
        return False
    if stripped[0].islower():
        return True
    first_token = stripped.split(maxsplit=1)[0]
    if BULLET_MARKER_RE.match(first_token):
        return True
    if RE_PART_REFERENCE.search(stripped) or RE_ITEM_REFERENCE.search(stripped):
        continuation = _extract_continuation(stripped)
        if continuation and continuation[0:1].islower():
            return True
    return False


def is_preceding_continuation(line: str) -> bool:
    """Return whether ``line`` ends with continuation punctuation or words."""
    stripped = line.strip()
    if not stripped:
        return False
    return bool(RE_PRECEDING_CONTINUATION.search(stripped))


__all__ = [
    "RE_ITEM_EXACT",
    "RE_ITEM_ONE",
    "RE_ITEM_ONE_A",
    "RE_ITEM_REFERENCE",
    "RE_PART",
    "RE_PART_ONE",
    "RE_PART_REFERENCE",
    "RE_PRECEDING_CONTINUATION",
    "ParsedSection",
    "SectionKind",
    "StructuralMatch",
    "StructuralRole",
    "is_continuation_prose",
    "is_exact_heading",
    "is_preceding_continuation",
    "match_structural_line",
    "parse_section_heading",
]
