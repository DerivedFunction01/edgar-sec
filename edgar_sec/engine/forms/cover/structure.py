"""Generic structural matching for cover, TOC, and body boundaries: representation-
neutral PART/ITEM heading mechanics only, since TOC patterns live in `toc.patterns`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from edgar_sec.engine.tables.toc.patterns import (
    RE_ITEM_REFERENCE,
    RE_PART_REFERENCE,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.tokens import (
    BULLET_MARKER_RE,
    BULLET_MARKERS,
    GLYPH_BULLET_MARKERS,
)

_HEADING_SEPARATOR_CHARS = ":.- |+\t" + "".join(sorted(BULLET_MARKERS))


class SectionKind(str, Enum):
    """Canonical structural role for an SEC filing section."""

    PART = "part"
    ITEM = "item"


@dataclass(frozen=True, slots=True)
class ParsedSection:
    """A parsed structural section heading or reference."""

    kind: SectionKind
    identifier: str
    canonical_label: str
    title: str = ""
    is_exact_heading: bool = True


class StructuralRole:
    """Stable names for generic structural match roles."""

    PART = "part"
    ITEM = "item"
    UNKNOWN = "unknown"


class StructuralMatch:
    """A single structural heading match with role and continuation info."""

    __slots__ = (
        "continuation_text",
        "is_exact_heading",
        "label",
        "line",
        "reference_count",
        "role",
    )

    def __init__(
        self,
        *,
        line: int,
        role: str,
        label: str,
        is_exact_heading: bool,
        reference_count: int,
        continuation_text: str = "",
    ) -> None:
        self.line = line
        self.role = role
        self.label = label
        self.is_exact_heading = is_exact_heading
        self.reference_count = reference_count
        self.continuation_text = continuation_text


# Roman numeral alternation for generic PART matching.
_ROMAN_PARTS = ("IV", "III", "II", "I", "V")
_ROMAN_PARTS_ALTERNATION = build_alternation(list(_ROMAN_PARTS), auto_escape=True)

# Exact PART heading: isolated after trimming, optional period, optional
# "(Continued)" marker. Prose such as "Part III. hereof." never matches.
RE_PART = re.compile(
    rf"^\s*PART\s+{_ROMAN_PARTS_ALTERNATION}\s*\.?\s*(?:\(\s*continued\s*\))?\s*$",
    re.IGNORECASE,
)

# Real ITEM headings (1, 1A, 1.01, 5.02, 9.01, etc.) carry a title-case title after an optional
# separator. TOC rows ("ITEM 1. BUSINESS ..... 1") fail because the title may
# contain dot leaders or a trailing page number.
RE_ITEM_EXACT = re.compile(
    r"^\s*ITEMS?\s+(?:\d+[A-Z]?(?:\.\d{1,2})?)\b\s*(?:[.:;\-]+\s*)?"
    r"(?:(?-i:[A-Z])[A-Za-z0-9,&'()\s-]*)?[:.]?\s*"
    r"(?:\(\s*continued\s*\))?\s*$",
    re.IGNORECASE,
)

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
    r"\b(?:PART|ITEM)\s+(?:[IVX]+|[0-9]+[A-Z]?)\b\s*(.*)",
    re.IGNORECASE,
)


def parse_section_heading(
    text: str,
    *,
    allow_inline: bool = False,
) -> ParsedSection | None:
    """Parse a structural Part or Item heading. Without `allow_inline`, prose like
    "as noted in Item 1" returns None; with it, `is_exact_heading=False`.
    """
    if not text:
        return None
    stripped = text.strip()

    part_match = _PART_HEADING_RE.match(stripped)
    if part_match:
        part_num = part_match.group(1).upper()
        raw_title = part_match.group(2).strip()
        title = raw_title.strip(_HEADING_SEPARATOR_CHARS)
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
        raw_title = item_match.group(2).strip()
        title = raw_title.strip(_HEADING_SEPARATOR_CHARS)
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


def match_structural_line(
    line: str,
    line_number: int,
) -> StructuralMatch | None:
    """Classify one line as a structural heading candidate, or None; `is_exact_heading`
    separates an isolated heading from prose containing a section reference.
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
        continuation = _extract_continuation(stripped)
        return StructuralMatch(
            line=line_number,
            role=StructuralRole.UNKNOWN,
            label=stripped,
            is_exact_heading=False,
            reference_count=reference_count,
            continuation_text=continuation,
        )

    return None


def is_exact_heading(line: str) -> bool:
    """Return whether ``line`` is an isolated PART/ITEM structural heading."""
    stripped = line.strip()
    if not stripped:
        return False
    return bool(RE_PART.match(stripped) or RE_ITEM_EXACT.match(stripped))


def is_continuation_prose(line: str) -> bool:
    """Whether `line` looks like prose continuing a previous sentence: rejects PART/ITEM
    references inside prose ("Part III. hereof.") or bulleted reference lists.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if is_exact_heading(stripped):
        return False
    if stripped[0].islower():
        return True
    parts = stripped.split(maxsplit=1)
    first_token = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""
    if BULLET_MARKER_RE.match(first_token):
        if not rest or rest[0].islower():
            return True
        if RE_PART_REFERENCE.search(stripped) or RE_ITEM_REFERENCE.search(stripped):
            return True
        if first_token in GLYPH_BULLET_MARKERS or first_token in {"*", "+", "-"}:
            return rest[0].islower()
        return False
    if RE_PART_REFERENCE.search(stripped) or RE_ITEM_REFERENCE.search(stripped):
        continuation = _extract_continuation(stripped)
        if continuation and continuation[0:1].islower():
            return True
    return False


def is_preceding_continuation(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(RE_PRECEDING_CONTINUATION.search(stripped))


def _extract_continuation(stripped: str) -> str:
    match = _SECTION_REFERENCE_RE.search(stripped)
    if match:
        return match.group(1).strip()
    return ""


__all__ = [
    "RE_ITEM_EXACT",
    "RE_ITEM_REFERENCE",
    "RE_PART",
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
