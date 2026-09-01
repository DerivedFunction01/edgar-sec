"""Template dispatcher routing table grids to specialized formatters based on scope."""

from __future__ import annotations

from .common import TemplateResult
from .cover import (
    checkbox_grid_template,
    cover_layout_template,
    single_row_horizontal_template,
)
from .presentation import (
    exhibit_index_template,
    side_by_side_template,
    sparse_status_matrix_template,
    uniform_text_table_template,
)
from .registration import registration_table_template
from .scope import TableScope


def apply_table_templates(
    table: object,
    source_grid: list[list[str]],
    *,
    scope: str | TableScope = TableScope.BODY,
) -> TemplateResult | None:
    """Try specialized table layout templates in precedence order.

    Args:
        table:       HTML table node.
        source_grid: 2D cell text matrix.
        scope:       Processing scope as a typed :class:`TableScope` or a
                     legacy string ('cover', 'toc', 'body').

    Returns:
        TemplateResult with rendered text and a ``bypass_guard`` flag that
        signals the caller should skip the numeric-density unwrap check.
        Returns ``None`` when no template matches.
    """
    typed_scope = TableScope.from_string(scope)

    # 1. Cover & Registration templates (activated exclusively for cover scope)
    if typed_scope is TableScope.COVER:
        res_reg = registration_table_template(source_grid)
        if res_reg:
            return TemplateResult(text=res_reg, bypass_guard=False)

        res_cover = cover_layout_template(source_grid)
        if res_cover:
            return TemplateResult(text=res_cover, bypass_guard=True)

        res_chk = checkbox_grid_template(source_grid)
        if res_chk:
            return TemplateResult(text=res_chk, bypass_guard=True)

        res_single = single_row_horizontal_template(source_grid)
        if res_single:
            return TemplateResult(text=res_single, bypass_guard=True)

    # 2. General financial & body table templates (side-by-side, uniform text)
    if typed_scope is not TableScope.TOC:
        res_product_status = sparse_status_matrix_template(source_grid)
        if res_product_status:
            return TemplateResult(text=res_product_status, bypass_guard=False)

        res_exhibit = exhibit_index_template(source_grid)
        if res_exhibit:
            return TemplateResult(text=res_exhibit, bypass_guard=True)

        res_side = side_by_side_template(table, source_grid)
        if res_side:
            return TemplateResult(text=res_side, bypass_guard=False)

        res_uniform = uniform_text_table_template(source_grid)
        if res_uniform:
            return TemplateResult(text=res_uniform, bypass_guard=False)

    return None


__all__ = ["TableScope", "apply_table_templates"]
