"""TOC span detection shared by cover, table, and body processing."""

from __future__ import annotations

import re
from dataclasses import dataclass

from defs.regex import build_alternation, compact_alternation
from defs.sec_forms.cover.structure import (
    RE_ITEM_REFERENCE,
    RE_PART_REFERENCE,
    is_continuation_prose,
)
from defs.sec_forms.page_markers import is_page_marker_line
from defs.text.tokens import BULLET_MARKERS


@dataclass(frozen=True, slots=True)
class TocEvidence:
    """Named evidence supporting a TOC span."""

    name: str
    line: int | None = None
    details: str = ""


@dataclass(frozen=True, slots=True)
class TocSpan:
    """An exclusive source span containing a detected table of contents."""

    start_line: int
    end_line: int
    start_offset: int
    end_offset: int
    method: str
    confidence: float
    evidence: tuple[TocEvidence, ...] = ()
    approximate: bool = False


# Exact TOC headings (including ASCII table borders | TABLE OF CONTENTS |).
RE_TOC_HEADING = re.compile(
    r"^\s*(?:[\|+]\s*)?(?:table\s+of\s+)?contents(?:\s*\([^)]*\))?(?:\s*[\|+])?\s*$",
    re.IGNORECASE,
)
_ITEM_CONJUNCTION = build_alternation(["and", "&", "-"], auto_escape=True)
RE_TOC_ITEM = re.compile(
    rf"^\s*(?:[\|+]\s*)?ITEMS?\s+\d+[A-Z]?(?:[\s,]+(?:{_ITEM_CONJUNCTION})?[\s,]*\d+[A-Z]?)*[\.\s]",
    re.IGNORECASE,
)
RE_TOC_PART_TEXT = re.compile(r"\bp\s*a\s*r\s*t\s+(?:[ivxlcdm]+|\d+)\b", re.IGNORECASE)

# Weak TOC heading words that require row/layout evidence.
WEAK_TOC_HEADINGS = ("index", "reference", "references")
_RE_WEAK_HEADING = re.compile(
    rf"^\s*(?:[\|+]\s*)?{compact_alternation(WEAK_TOC_HEADINGS)}(?:\s*[\|+])?\s*$",
    re.IGNORECASE,
)

# Dot-leader pattern for TOC rows.
RE_TOC_LEADER = re.compile(r"\s\.{3,}\s")
# Page-number suffix pattern (digits or roman numerals).
RE_PAGE_SUFFIX = re.compile(
    r"(?:\b[A-Z])?[\.\-\s]?(?:\d+|[ivxlcdm]+\b)(?:\s*[\|+])?\s*$", re.IGNORECASE
)

_RE_TAGGED_TABLE = re.compile(r"<TABLE\b", re.IGNORECASE)
_RE_TAGGED_TABLE_END = re.compile(r"</TABLE\s*>", re.IGNORECASE)

_RE_NON_ALPHANUM = re.compile(r"[^a-z0-9]+")
_RE_MULTI_SPACE = re.compile(r"\s+")


def normalize_for_matching(text: str) -> str:
    """Normalize text into clean lowercase single-spaced alphanumeric tokens."""
    if not text:
        return ""
    sanitized = _RE_NON_ALPHANUM.sub(" ", text.lower())
    return _RE_MULTI_SPACE.sub(" ", sanitized).strip()


def is_toc_row(line: str) -> bool:
    """Return whether ``line`` looks like a TOC row.

    TOC rows typically contain a section label followed by dot leaders and a
    trailing page number.
    """
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    if RE_TOC_LEADER.search(stripped) and RE_PAGE_SUFFIX.search(stripped):
        return bool(
            RE_PART_REFERENCE.search(stripped) or RE_ITEM_REFERENCE.search(stripped)
        )
    return False


def _line_offset(lines: list[str], line: int) -> int:
    return sum(len(value) + 1 for value in lines[:line])


def _row_lines(lines: list[str], start: int, limit: int) -> list[int]:
    rows: list[int] = []
    for index in range(start, limit):
        line = lines[index].strip().strip("|+")
        if not line or is_page_marker_line(line):
            # Skip blank lines and page markers; they may split multi-page TOCs
            continue
        if is_toc_row(line) or (
            RE_TOC_ITEM.match(line)
            and (RE_TOC_LEADER.search(line) or RE_PAGE_SUFFIX.search(line))
        ):
            rows.append(index)
    return rows


def score_block_toc_density(
    normalized_block: str,
    norm_toc_keywords: tuple[str, ...],
) -> tuple[int, tuple[str, ...]]:
    """Count matches of known TOC keywords in a normalized text block."""
    if not normalized_block or not norm_toc_keywords:
        return 0, ()
    hits = tuple(term for term in norm_toc_keywords if term in normalized_block)
    return len(hits), hits


def is_anachronistic_late_item(
    line: str,
    late_item_re: re.Pattern | None = None,
    norm_late_names: tuple[str, ...] = (),
) -> bool:
    """True if line matches a late item (Part II+, Item 5+) indicating TOC anachronism."""
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    if late_item_re is not None and late_item_re.match(stripped):
        return True
    if norm_late_names:
        norm_line = normalize_for_matching(stripped)
        if (
            len(stripped) <= 120
            and not is_continuation_prose(stripped)
            and any(name in norm_line for name in norm_late_names)
        ):
            return True
    return False


def consume_toc_residue(
    lines: list[str],
    start_index: int,
    limit: int,
    derived_taxonomy: dict | None = None,
) -> int:
    """Advance past trailing TOC residue until substantive body prose begins."""
    curr = start_index
    late_item_re = derived_taxonomy.get("late_item_re") if derived_taxonomy else None
    norm_late_names = (
        derived_taxonomy.get("norm_late_names", ()) if derived_taxonomy else ()
    )
    norm_early_names = (
        derived_taxonomy.get("norm_early_names", ()) if derived_taxonomy else ()
    )

    while curr < limit:
        line = lines[curr].strip()
        if not line or line.startswith(("+---", "====")):
            curr += 1
            continue

        clean_line = line.strip("|+").strip()
        if not clean_line:
            curr += 1
            continue

        # Page markers splitting a multi-page TOC are transparent
        if is_page_marker_line(clean_line):
            curr += 1
            continue

        norm_line = normalize_for_matching(clean_line)

        # Footnotes at the bottom of the TOC (*, Note:)
        if line.startswith(("*", "Note:", "NOTE:")):
            curr += 1
            continue

        # Stop if line is long operating prose
        if len(clean_line) > 200:
            break

        # Stop if line matches an early item with following body prose
        if (
            any(name in norm_line for name in norm_early_names)
            and curr + 1 < limit
            and is_continuation_prose(lines[curr + 1])
        ):
            break

        # If it's a standalone Part I / Item 1 heading, stop
        if (
            clean_line.upper() in ("PART I", "PART 1") or RE_TOC_ITEM.match(clean_line)
        ) and (
            curr + 1 < limit
            and not (
                is_toc_row(lines[curr + 1]) or RE_TOC_LEADER.search(lines[curr + 1])
            )
        ):
            break

        # If it's a TOC continuation heading, consume
        if RE_TOC_HEADING.match(clean_line) or _RE_WEAK_HEADING.match(clean_line):
            curr += 1
            continue

        # If it's a TOC row or dot leader, keep consuming
        if is_toc_row(clean_line) or RE_TOC_LEADER.search(clean_line):
            curr += 1
            continue

        # If it's a late item without prose, keep consuming
        if is_anachronistic_late_item(clean_line, late_item_re, norm_late_names):
            curr += 1
            continue

        # Single bullet marker or short page number
        if clean_line in BULLET_MARKERS or (
            clean_line.isdigit() and len(clean_line) <= 4
        ):
            curr += 1
            continue

        break

    return curr


def find_toc_span(
    text: str,
    *,
    start_line: int = 0,
    max_lines: int | None = None,
    minimum_rows: int = 2,
    derived_taxonomy: dict | None = None,
) -> TocSpan | None:
    """Find a conservative TOC span in text using headings, density, and anachronism."""
    lines = text.splitlines()
    if not lines or start_line >= len(lines):
        return None
    limit = min(len(lines), max_lines or len(lines))
    start_line = max(0, start_line)

    norm_toc_keywords = (
        derived_taxonomy.get("norm_toc_keywords", ()) if derived_taxonomy else ()
    )
    late_item_re = derived_taxonomy.get("late_item_re") if derived_taxonomy else None
    norm_late_names = (
        derived_taxonomy.get("norm_late_names", ()) if derived_taxonomy else ()
    )

    # 1. Explicit TOC Headings
    for index in range(start_line, limit):
        heading = RE_TOC_HEADING.match(lines[index]) or _RE_WEAK_HEADING.match(
            lines[index]
        )
        if not heading:
            continue
        rows = _row_lines(lines, index + 1, limit)
        if len(rows) < minimum_rows:
            continue
        end_line = consume_toc_residue(
            lines, rows[-1] + 1, limit, derived_taxonomy=derived_taxonomy
        )
        evidence = [
            TocEvidence(
                name="toc_heading",
                line=index,
                details=lines[index].strip(),
            ),
            TocEvidence(
                name="toc_rows",
                line=rows[0],
                details=f"{len(rows)} TOC-like rows",
            ),
        ]
        method = "heading_rows"
        if _RE_WEAK_HEADING.match(lines[index]):
            method = "weak_heading_rows"
            evidence.append(
                TocEvidence(
                    name="weak_heading_requires_rows",
                    line=index,
                    details="INDEX/REFERENCE promoted by row evidence",
                )
            )
        return TocSpan(
            start_line=index,
            end_line=end_line,
            start_offset=_line_offset(lines, index),
            end_offset=_line_offset(lines, end_line),
            method=method,
            confidence=0.92 if method == "heading_rows" else 0.78,
            evidence=tuple(evidence),
        )

    # 2. Tagged Table TOC (<TABLE> ... </TABLE>)
    for index in range(start_line, limit):
        if not _RE_TAGGED_TABLE.search(lines[index]):
            continue
        end = next(
            (
                candidate
                for candidate in range(index + 1, limit)
                if _RE_TAGGED_TABLE_END.search(lines[candidate])
            ),
            None,
        )
        if end is None:
            continue
        rows = _row_lines(lines, index, end + 1)
        if len(rows) < minimum_rows:
            continue

        # Bridge across page markers into a second <TABLE> continuation block.
        # Only valid if the gap contains nothing but blank lines and page markers.
        merged_end = end
        scan = end + 1
        while scan < limit:
            gap_line = lines[scan].strip()
            if not gap_line or is_page_marker_line(gap_line):
                scan += 1
                continue
            if _RE_TAGGED_TABLE.search(gap_line):
                # Found a continuation <TABLE>; find its closing tag
                cont_end = next(
                    (
                        c
                        for c in range(scan + 1, limit)
                        if _RE_TAGGED_TABLE_END.search(lines[c])
                    ),
                    None,
                )
                if cont_end is not None:
                    cont_rows = _row_lines(lines, scan, cont_end + 1)
                    if cont_rows:
                        rows = rows + cont_rows
                        merged_end = cont_end
                        scan = cont_end + 1
                        continue
            break

        end_line = consume_toc_residue(
            lines, merged_end + 1, limit, derived_taxonomy=derived_taxonomy
        )
        merged = merged_end != end
        return TocSpan(
            start_line=index,
            end_line=end_line,
            start_offset=_line_offset(lines, index),
            end_offset=_line_offset(lines, end_line),
            method="tagged_table_merged" if merged else "tagged_table",
            confidence=0.88,
            evidence=(
                TocEvidence(
                    name="tagged_toc_table",
                    line=index,
                    details=f"{len(rows)} TOC-like rows inside TABLE"
                    + (" (merged across page break)" if merged else ""),
                ),
            ),
        )

    # 3. Density-Based TOC (3+ keyword hits containing at least one late item/name)
    if norm_toc_keywords and norm_late_names:
        for index in range(start_line, min(limit, start_line + 60)):
            line = lines[index].strip()
            if not line:
                continue
            norm_line = normalize_for_matching(line)
            hits_count, hit_terms = score_block_toc_density(
                norm_line, norm_toc_keywords
            )
            # Require at least 3 hits AND at least one late-item indicator
            has_late_hit = any(name in norm_line for name in norm_late_names) or (
                late_item_re and late_item_re.search(line)
            )
            if hits_count >= 3 and has_late_hit:
                rows = _row_lines(lines, index, limit)
                last_row = rows[-1] if rows else index + 1
                end_line = consume_toc_residue(
                    lines, last_row + 1, limit, derived_taxonomy=derived_taxonomy
                )
                return TocSpan(
                    start_line=index,
                    end_line=end_line,
                    start_offset=_line_offset(lines, index),
                    end_offset=_line_offset(lines, end_line),
                    method="density_score",
                    confidence=0.85,
                    evidence=(
                        TocEvidence(
                            name="keyword_density_toc",
                            line=index,
                            details=f"Density hits: {', '.join(hit_terms[:4])}",
                        ),
                    ),
                )

    # 4. Temporal Anachronism (Late-Item Appearance in Opening Lines)
    if late_item_re or norm_late_names:
        for index in range(start_line, min(limit, start_line + 40)):
            if is_anachronistic_late_item(lines[index], late_item_re, norm_late_names):
                rows = _row_lines(lines, index, limit)
                last_row = rows[-1] if rows else index + 1
                end_line = consume_toc_residue(
                    lines, last_row + 1, limit, derived_taxonomy=derived_taxonomy
                )
                return TocSpan(
                    start_line=index,
                    end_line=end_line,
                    start_offset=_line_offset(lines, index),
                    end_offset=_line_offset(lines, end_line),
                    method="anachronism_late_item",
                    confidence=0.82,
                    evidence=(
                        TocEvidence(
                            name="anachronistic_late_item",
                            line=index,
                            details=f"Late item found before body: {lines[index].strip()[:50]}",
                        ),
                    ),
                )

    # 5. Aligned Dot-Leader Rows Without Explicit Heading
    for index in range(start_line, limit):
        if not is_toc_row(lines[index]):
            continue
        rows = _row_lines(lines, index, limit)
        if len(rows) < minimum_rows:
            continue
        end_line = consume_toc_residue(
            lines, rows[-1] + 1, limit, derived_taxonomy=derived_taxonomy
        )
        return TocSpan(
            start_line=index,
            end_line=end_line,
            start_offset=_line_offset(lines, index),
            end_offset=_line_offset(lines, end_line),
            method="aligned_rows",
            confidence=0.7,
            evidence=(
                TocEvidence(
                    name="toc_rows_without_heading",
                    line=index,
                    details=f"{len(rows)} TOC-like rows",
                ),
            ),
            approximate=True,
        )

    return None


__all__ = [
    "RE_PAGE_SUFFIX",
    "RE_TOC_HEADING",
    "RE_TOC_ITEM",
    "RE_TOC_LEADER",
    "RE_TOC_PART_TEXT",
    "WEAK_TOC_HEADINGS",
    "TocEvidence",
    "TocSpan",
    "consume_toc_residue",
    "find_toc_span",
    "is_anachronistic_late_item",
    "is_toc_row",
    "normalize_for_matching",
    "score_block_toc_density",
]
