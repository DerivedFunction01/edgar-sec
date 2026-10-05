"""Lightweight DOM grid extraction for pre-filtering false tables without CSS parsing.
A cheap pre-pass, not a cheaper full render: it returns `None` the moment the table is too complex
to fully understand, so a wrong answer is never produced for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cell import normalize_cell_whitespace

if TYPE_CHECKING:
    from edgar_sec.engine.document.html.tree import FastHtmlNode


def _has_nested_table(raw_node) -> bool:  # type: ignore[no-untyped-def]
    """Return True if *raw_node* has any ``<table>`` descendant (iterative DFS)."""
    stack = [c for c in raw_node.iter(include_text=False) if c.tag]
    while stack:
        n = stack.pop()
        if (n.tag or "").lower() == "table":
            return True
        stack.extend(c for c in n.iter(include_text=False) if c.tag)
    return False


def quick_extract_table_grid(
    table_node: FastHtmlNode,
) -> tuple[tuple[str, ...], ...] | None:
    """Fast text-only DOM scan to detect obvious false tables without CSS parsing.
    Returns ``None`` when the table uses spans or nests a ``<table>``, ``()`` when no cell has text.
    """
    rows: list[tuple[str, ...]] = []
    max_cols = 0

    for section in table_node.iter_children():
        tag = section.tag
        if tag in ("tbody", "thead", "tfoot"):
            tr_nodes = list(section.iter_children())
        elif tag == "tr":
            tr_nodes = [section]
        else:
            continue

        for tr in tr_nodes:
            if tr.tag != "tr":
                continue
            cells: list[str] = []
            for td in tr.iter_children():
                if td.tag not in ("td", "th"):
                    continue
                attrs = td.raw_node.attributes or {}
                try:
                    if int(attrs.get("colspan", "1")) > 1:
                        return None
                    if int(attrs.get("rowspan", "1")) > 1:
                        return None
                except ValueError:
                    return None
                if _has_nested_table(td.raw_node):
                    return None
                raw_cell_text = td.text(strip=True) or ""
                cells.append(normalize_cell_whitespace(raw_cell_text))
            if cells:
                rows.append(tuple(cells))
                max_cols = max(max_cols, len(cells))

    if not rows:
        return ()

    # Pad rows to uniform width for is_false_grid compatibility
    return tuple(row + ("",) * (max_cols - len(row)) for row in rows)
