"""Main TOC span detection logic."""

from __future__ import annotations

from defs.sec_forms.page_markers import is_page_marker_line

from .analysis import (
    _row_lines,
    is_anachronistic_late_item,
    is_toc_row,
    normalize_for_matching,
    score_block_toc_density,
)
from .models import TocEvidence, TocSpan
from .patterns import (
    _RE_TAGGED_TABLE,
    _RE_TAGGED_TABLE_END,
    _RE_WEAK_HEADING,
    RE_TOC_HEADING,
)
from .residue import consume_toc_residue


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

    for index in range(start_line, limit):
        heading = RE_TOC_HEADING.match(lines[index]) or _RE_WEAK_HEADING.match(
            lines[index]
        )
        if not heading:
            continue
        rows = _row_lines(lines, index + 1, limit, page_marker_lines)
        if len(rows) < minimum_rows:
            continue
        end_line = consume_toc_residue(
            lines,
            rows[-1] + 1,
            limit,
            derived_taxonomy=derived_taxonomy,
            page_marker_lines=page_marker_lines,
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
        rows = _row_lines(lines, index, end + 1, page_marker_lines)
        if len(rows) < minimum_rows:
            continue

        merged_end = end
        scan = end + 1
        while scan < limit:
            gap_line = lines[scan].strip()
            if (
                not gap_line
                or scan in page_marker_lines
                or is_page_marker_line(gap_line)
            ):
                scan += 1
                continue
            if _RE_TAGGED_TABLE.search(gap_line):
                cont_end = next(
                    (
                        c
                        for c in range(scan + 1, limit)
                        if _RE_TAGGED_TABLE_END.search(lines[c])
                    ),
                    None,
                )
                if cont_end is not None:
                    cont_rows = _row_lines(lines, scan, cont_end + 1, page_marker_lines)
                    if cont_rows:
                        rows = rows + cont_rows
                        merged_end = cont_end
                        scan = cont_end + 1
                        continue
            break

        end_line = consume_toc_residue(
            lines,
            merged_end + 1,
            limit,
            derived_taxonomy=derived_taxonomy,
            page_marker_lines=page_marker_lines,
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


def _line_offset(lines: list[str], line: int) -> int:
    return sum(len(value) + 1 for value in lines[:line])


__all__ = ["find_toc_span"]
