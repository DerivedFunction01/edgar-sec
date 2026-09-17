"""Lightweight DOM grid extraction for pre-filtering false tables without CSS parsing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from defs.text.html import FastHtmlNode


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

    Returns
    -------
    None
        The table uses ``colspan``/``rowspan`` or has nested ``<table>`` elements;
        full ``extract_source_table`` extraction is required.
    ``()`` (empty tuple)
        No cells with visible text found.
    Grid of raw cell texts
        Caller should pass this to :func:`~defs.tables.false_tables.is_false_grid`
        and, on a True verdict, to :func:`~defs.tables.false_tables.unwrap_grid`.
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
                # Bail on complex spans — full extraction required
                try:
                    if int(attrs.get("colspan", "1")) > 1:
                        return None
                    if int(attrs.get("rowspan", "1")) > 1:
                        return None
                except ValueError:
                    return None
                # Bail when a nested table is present
                if _has_nested_table(td.raw_node):
                    return None
                cells.append(td.text(strip=True) or "")
            if cells:
                rows.append(tuple(cells))
                max_cols = max(max_cols, len(cells))

    if not rows:
        return ()

    # Pad rows to uniform width for is_false_grid compatibility
    return tuple(row + ("",) * (max_cols - len(row)) for row in rows)
