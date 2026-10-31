"""TOC span detection: a strict method ladder, highest confidence first. Heading plus
rows, a rendered `<TABLE>` of aligned rows, keyword density corroborated by a late
item, a lone late item, then bare aligned rows.
"""

from __future__ import annotations

from collections import Counter

from edgar_sec.engine.document.page_markers.detector import is_page_marker_line
from edgar_sec.engine.tables.protection.tags import (
    TAGGED_TABLE_CLOSE_RE,
    TAGGED_TABLE_OPEN_RE,
)
from edgar_sec.engine.tables.toc.patterns import (
    RE_PAGE_SUFFIX,
    RE_TOC_ITEM_ROW,
    is_toc_row,
    looks_like_toc_row,
)
from edgar_sec.foundation.text.tokens import roman_to_int

from .analysis import (
    _line_offset,
    _row_lines,
    _table_toc_rows,
    is_anachronistic_late_item,
    normalize_for_matching,
    score_block_toc_density,
)
from .models import TocEvidence, TocSpan
from .patterns import (
    _RE_WEAK_HEADING,
    RE_TOC_HEADING,
    RE_TOC_PART_ROW,
)
from .residue import consume_toc_residue

# A heading whose rows begin beyond this window is mid-document navigation
# text, not a TOC start.
_MAX_HEADING_ROW_GAP = 10


def _table_delta(line: str) -> int:
    return len(TAGGED_TABLE_OPEN_RE.findall(line)) - len(
        TAGGED_TABLE_CLOSE_RE.findall(line)
    )


def _build_table_depths(lines: list[str]) -> list[int]:
    """Return cumulative ``<TABLE>`` nesting depth after each line."""
    depths: list[int] = []
    running = 0
    for line in lines:
        running += _table_delta(line)
        depths.append(running)
    return depths


def _enclosing_table_end(
    lines: list[str], last_row: int, limit: int, depths: list[int]
) -> int | None:
    """The close line of the table enclosing the TOC row span, claimed only when the
    last row sits inside an open `<TABLE>` and the close is within the limit.
    """
    if last_row >= len(depths) or depths[last_row] <= 0:
        return None
    running = depths[last_row]
    for candidate in range(last_row + 1, min(limit, len(lines))):
        running += _table_delta(lines[candidate])
        if running <= 0:
            return candidate
    return None


def _merge_continuation_tables(
    lines: list[str],
    table_end: int,
    limit: int,
    page_marker_lines: set[int],
    rows: list[int],
) -> tuple[int, list[int]]:
    """Claim page-break-split continuation tables after a close: gap lines are skipped,
    a following table of TOC-like rows is claimed, anything else ends the merge.
    """
    merged_end = table_end
    scan = table_end + 1
    while scan < limit:
        gap_line = lines[scan].strip()
        if not gap_line or scan in page_marker_lines or is_page_marker_line(gap_line):
            scan += 1
            continue
        if TAGGED_TABLE_OPEN_RE.search(gap_line):
            cont_end = next(
                (
                    candidate
                    for candidate in range(scan + 1, limit)
                    if TAGGED_TABLE_CLOSE_RE.search(lines[candidate])
                ),
                None,
            )
            if cont_end is not None:
                cont_rows = _row_lines(lines, scan, cont_end + 1, page_marker_lines)
                if not cont_rows:
                    cont_rows = _table_toc_rows(lines, scan, cont_end + 1)
                if cont_rows:
                    rows = rows + cont_rows
                    merged_end = cont_end
                    scan = cont_end + 1
                    continue
        break
    return merged_end, rows


def _sequence_key(line: str, current_part: int) -> tuple[int, int] | int | None:
    """The monotonic ordering key for a PART/ITEM row: PART resets the item counter,
    ITEM returns `(part, item * 100 + letter)` so Item 1 < 1A < 2 within a part.
    """
    part = RE_TOC_PART_ROW.match(line)
    if part:
        token = part.group(1).lower()
        roman_value = roman_to_int(token)
        if roman_value is not None:
            return roman_value
        if token.isdigit():
            return int(token)
        return None
    item = RE_TOC_ITEM_ROW.match(line)
    if item:
        number = int(item.group(1))
        suffix = item.group(2)
        letter = ord(suffix.lower()) - 96 if suffix else 0
        return (current_part, number * 100 + letter)
    return None


def _refine_toc_end(
    lines: list[str], start_line: int, end_line: int
) -> tuple[int, tuple[TocEvidence, ...]]:
    """Extend aligned TOC residue, then trim at a sequence reset."""
    evidence: list[TocEvidence] = []
    page_columns = [
        RE_PAGE_SUFFIX.search(lines[index]).start()
        for index in range(start_line, min(end_line, len(lines)))
        if looks_like_toc_row(lines[index]) and RE_PAGE_SUFFIX.search(lines[index])
    ]
    if page_columns:
        modal_column = Counter(page_columns).most_common(1)[0][0]
        aligned_after: list[int] = []
        for index in range(end_line, min(end_line + 15, len(lines))):
            match = RE_PAGE_SUFFIX.search(lines[index])
            if (
                match
                and looks_like_toc_row(lines[index])
                and abs(match.start() - modal_column) <= 2
            ):
                aligned_after.append(index)
        if len(aligned_after) >= 2:
            end_line = aligned_after[-1] + 1
            evidence.append(
                TocEvidence(
                    name="toc_alignment_extension",
                    line=aligned_after[0],
                    details=f"{len(aligned_after)} rows match modal page column",
                )
            )

    current_part = 0
    last_key: tuple[int, int] | None = None
    for index in range(start_line, min(end_line, len(lines))):
        parsed = _sequence_key(lines[index], current_part)
        if isinstance(parsed, int):
            current_part = parsed
            key = (current_part, 0)
        else:
            key = parsed
        if key is None:
            continue
        if last_key is not None and key < last_key:
            end_line = index
            evidence.append(
                TocEvidence(
                    name="toc_sequence_reset",
                    line=index,
                    details="part/item sequence reset after TOC rows",
                )
            )
            break
        last_key = key
    return end_line, tuple(evidence)


def find_toc_span(
    text: str,
    *,
    start_line: int = 0,
    max_lines: int | None = None,
    minimum_rows: int = 2,
    derived_taxonomy: dict | None = None,
    page_analysis: object | None = None,
) -> TocSpan | None:
    """Find a conservative TOC span in text using headings, density, and anachronism."""
    lines = text.splitlines()
    if not lines or start_line >= len(lines):
        return None
    limit = min(len(lines), max_lines or len(lines))
    start_line = max(0, start_line)
    page_marker_lines = {
        marker.start_line
        for marker in getattr(page_analysis, "markers", ())
        if marker.start_line is not None
    }

    matcher = derived_taxonomy.get("matcher") if derived_taxonomy else None
    norm_toc_keywords = (
        matcher
        if matcher is not None
        else (derived_taxonomy.get("norm_toc_keywords", ()) if derived_taxonomy else ())
    )
    late_item_re = derived_taxonomy.get("late_item_re") if derived_taxonomy else None
    norm_late_names = (
        matcher
        if matcher is not None
        else (derived_taxonomy.get("norm_late_names", ()) if derived_taxonomy else ())
    )

    depths: list[int] | None = None
    for index in range(start_line, limit):
        heading = RE_TOC_HEADING.match(lines[index]) or _RE_WEAK_HEADING.match(
            lines[index]
        )
        if not heading:
            continue
        rows = _row_lines(lines, index + 1, limit, page_marker_lines)
        if len(rows) < minimum_rows:
            continue
        if rows[0] - index > _MAX_HEADING_ROW_GAP:
            continue
        if depths is None:
            depths = _build_table_depths(lines)
        table_end = _enclosing_table_end(lines, rows[-1], limit, depths)
        table_evidence: list[TocEvidence] = []
        residue_start = rows[-1] + 1
        if table_end is not None:
            close = table_end
            table_end, rows = _merge_continuation_tables(
                lines, table_end, limit, page_marker_lines, rows
            )
            residue_start = table_end + 1
            table_evidence.append(
                TocEvidence(
                    name="toc_table_boundary",
                    line=table_end,
                    details="TOC rows claimed through enclosing TABLE close"
                    + (" (merged across page break)" if table_end != close else ""),
                )
            )
        end_line = consume_toc_residue(
            lines,
            residue_start,
            limit,
            derived_taxonomy=derived_taxonomy,
            page_marker_lines=page_marker_lines,
        )
        end_line, refinement_evidence = _refine_toc_end(lines, index, end_line)
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
        evidence.extend(table_evidence)
        evidence.extend(refinement_evidence)
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

    for index in range(start_line, limit):
        if not TAGGED_TABLE_OPEN_RE.search(lines[index]):
            continue
        end = next(
            (
                candidate
                for candidate in range(index + 1, limit)
                if TAGGED_TABLE_CLOSE_RE.search(lines[candidate])
            ),
            None,
        )
        if end is None:
            continue
        rows = _row_lines(lines, index, end + 1, page_marker_lines)
        if len(rows) < minimum_rows:
            rows = _table_toc_rows(lines, index, end + 1)
        if len(rows) < minimum_rows:
            continue

        merged_end, rows = _merge_continuation_tables(
            lines, end, limit, page_marker_lines, rows
        )
        merged = merged_end != end
        end_line = consume_toc_residue(
            lines,
            merged_end + 1,
            limit,
            derived_taxonomy=derived_taxonomy,
            page_marker_lines=page_marker_lines,
        )
        end_line, refinement_evidence = _refine_toc_end(lines, index, end_line)
        return TocSpan(
            start_line=index,
            end_line=end_line,
            start_offset=_line_offset(lines, index),
            end_offset=_line_offset(lines, end_line),
            method="tagged_table_merged" if merged else "tagged_table",
            confidence=0.88,
            evidence=refinement_evidence
            + (
                TocEvidence(
                    name="tagged_toc_table",
                    line=index,
                    details=f"{len(rows)} TOC-like rows inside TABLE"
                    + (" (merged across page break)" if merged else ""),
                ),
            ),
        )

    if norm_toc_keywords and norm_late_names:
        for index in range(start_line, min(limit, start_line + 60)):
            line = lines[index].strip()
            if not line:
                continue
            norm_line = normalize_for_matching(line)
            hits_count, hit_terms = score_block_toc_density(
                norm_line, norm_toc_keywords
            )
            has_late_hit = (
                matcher.has_any(norm_line, ["late_names"])
                if matcher is not None
                else any(name in norm_line for name in norm_late_names)
            ) or bool(late_item_re and late_item_re.search(line))

            if hits_count >= 3 and has_late_hit:
                rows = _row_lines(lines, index, limit, page_marker_lines)
                last_row = rows[-1] if rows else index + 1
                end_line = consume_toc_residue(
                    lines,
                    last_row + 1,
                    limit,
                    derived_taxonomy=derived_taxonomy,
                    page_marker_lines=page_marker_lines,
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

    if late_item_re or norm_late_names:
        for index in range(start_line, min(limit, start_line + 40)):
            if is_anachronistic_late_item(lines[index], late_item_re, norm_late_names):
                rows = _row_lines(lines, index, limit, page_marker_lines)
                last_row = rows[-1] if rows else index + 1
                end_line = consume_toc_residue(
                    lines,
                    last_row + 1,
                    limit,
                    derived_taxonomy=derived_taxonomy,
                    page_marker_lines=page_marker_lines,
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

    for index in range(start_line, limit):
        if not is_toc_row(lines[index]):
            continue
        rows = _row_lines(lines, index, limit, page_marker_lines)
        if len(rows) < minimum_rows:
            continue
        end_line = consume_toc_residue(
            lines,
            rows[-1] + 1,
            limit,
            derived_taxonomy=derived_taxonomy,
            page_marker_lines=page_marker_lines,
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


__all__ = ["find_toc_span"]
