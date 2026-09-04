"""Generic structural matching for cover, TOC, and body boundaries.

Owns only representation-neutral PART/ITEM heading mechanics. TOC-specific
patterns live in ``defs.sec_forms.cover.toc`` to keep this module generic and
free of annual-report-specific phrasing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from defs.regex import build_alternation
from defs.text.tokens import RE_BULLET_PREFIX


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

# PART I specifically.
RE_PART_ONE = re.compile(
    r"^\s*PART\s+I\s*\.?\s*(?:\(\s*continued\s*\))?\s*$", re.IGNORECASE
)

# Real ITEM 1 / ITEM 1A headings carry a title-case title after an optional
# separator. TOC rows ("ITEM 1. BUSINESS ..... 1") fail because the title may
# contain dot leaders or a trailing page number.
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


def parse_section_heading(
    text: str,
    *,
    allow_inline: bool = False,
) -> ParsedSection | None:
    """Parse a structural Part or Item heading.

    Guarantees:
    - By default (``allow_inline=False``), requires line-leading structural tokens
      (e.g., 'Item 1. Business', '| PART II |'). Leading prose or filler words
      ('as noted in Item 1', 'pursuant to Item 7') return ``None``.
    - Captures the canonical identifier ('I', 'II', '1', '1A', '7.01') and any trailing title.
    - When ``allow_inline=True``, recognizes prose mentions but flags
      ``is_exact_heading=False``.
    """
    if not text:
        return None
    stripped = text.strip()

    # 1. Exact leading PART heading
    part_match = _PART_HEADING_RE.match(stripped)
    if part_match:
        part_num = part_match.group(1).upper()
        raw_title = part_match.group(2).strip()
        title = raw_title.strip(":.- |+•\t")
        return ParsedSection(
            kind=SectionKind.PART,
            identifier=part_num,
            canonical_label=f"PART {part_num}",
            title=title,
            is_exact_heading=True,
        )

    # 2. Exact leading ITEM heading
    item_match = _ITEM_HEADING_RE.match(stripped)
    if item_match:
        item_num = item_match.group(1).upper()
        raw_title = item_match.group(2).strip()
        title = raw_title.strip(":.- |+•\t")
        return ParsedSection(
            kind=SectionKind.ITEM,
            identifier=item_num,
            canonical_label=f"ITEM {item_num}",
            title=title,
            is_exact_heading=True,
        )

    # 3. Inline reference fallback
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
    """Classify a single line as a generic structural heading candidate.

    Returns ``None`` when the line is not a structural candidate. Returns a
    ``StructuralMatch`` otherwise, with ``is_exact_heading`` indicating whether
    the line is an isolated heading rather than prose that happens to contain a
    section reference.
    """
    stripped = line.strip()
    if not stripped:
        return None

    part_refs = len(RE_PART_REFERENCE.findall(stripped))
    item_refs = len(RE_ITEM_REFERENCE.findall(stripped))
    reference_count = part_refs + item_refs

    # Exact PART heading.
    if RE_PART.match(stripped):
        return StructuralMatch(
            line=line_number,
            role=StructuralRole.PART,
            label=stripped,
            is_exact_heading=True,
            reference_count=part_refs,
        )

    # Exact ITEM 1 / ITEM 1A heading.
    if RE_ITEM_ONE.match(stripped) or RE_ITEM_ONE_A.match(stripped):
        return StructuralMatch(
            line=line_number,
            role=StructuralRole.ITEM,
            label=stripped,
            is_exact_heading=True,
            reference_count=item_refs,
        )

    # Not an exact heading, but contains section references.
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
    return bool(
        RE_PART.match(stripped)
        or RE_ITEM_ONE.match(stripped)
        or RE_ITEM_ONE_A.match(stripped)
    )


def is_continuation_prose(line: str) -> bool:
    """Return whether ``line`` looks like prose continuing a previous sentence.

    Used to reject PART/ITEM references embedded in incorporated-reference
    prose such as ``Part III. hereof.`` or bulleted/numbered reference lists.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if is_exact_heading(stripped):
        return False
    if stripped[0].islower():
        return True
    first_token = stripped.split(maxsplit=1)[0]
    if RE_BULLET_PREFIX.match(first_token):
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


def _extract_continuation(stripped: str) -> str:
    """Extract the text after a section reference token."""
    match = re.search(
        r"\b(?:PART|ITEM)\s+(?:[IVX]+|[0-9]+[A-Z]?)\b\s*(.*)",
        stripped,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return ""


__all__ = [
    "RE_ITEM_ONE",
    "RE_ITEM_ONE_A",
    "RE_ITEM_REFERENCE",
    "RE_PART",
    "RE_PART_ONE",
    "RE_PART_REFERENCE",
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
