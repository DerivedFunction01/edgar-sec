"""Template dispatcher routing table grids to specialized formatters based on scope."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .common import TemplateResult
from .cover import (
    checkbox_grid_template,
    cover_layout_template,
    single_row_horizontal_template,
)
from .exhibit_index import exhibit_index_template
from .presentation import (
    definition_table_template,
    footnote_template,
    linked_index_template,
    marked_list_template,
    side_by_side_template,
    sparse_status_matrix_template,
    titled_period_table_template,
    two_column_prose_template,
    uniform_text_table_template,
)
from .registration import registration_table_template
from .scope import TableScope
from .shares_purchased import shares_purchased_template

if TYPE_CHECKING:
    from defs.sec_forms.context import SectionContext, TableContext


def apply_table_templates(
    table: object,
    source_grid: list[list[str]],
    *,
    scope: str | TableScope = TableScope.BODY,
    section_context: SectionContext | None = None,
    table_context: TableContext | None = None,
) -> TemplateResult | None:
    """Try specialized table layout templates in precedence order.

    Args:
        table: BeautifulSoup table node.
        source_grid: Two-dimensional list of extracted cell strings.
        scope: Logical table scope (``"cover"``, ``"toc"``, ``"body"``).
        section_context: Optional logical section context for the table.
        table_context: Optional representation-neutral table context.
            Currently provenance-only; templates opt in explicitly.

    Returns:
        TemplateResult with rendered text and a ``bypass_guard`` flag that
        signals the caller should skip the numeric-density unwrap check.
        Returns ``None`` when no template matches.
    """
    typed_scope = TableScope.from_string(scope)
    effective_section = section_context or (
        table_context.section if table_context is not None else None
    )
    if typed_scope is TableScope.BODY and effective_section is not None:
        if (
            effective_section.cover_scope is not None
            and effective_section.cover_scope.active
        ):
            typed_scope = TableScope.COVER
        elif effective_section.scope is not None:
            typed_scope = effective_section.scope

    # 1. Cover & Registration templates (cover scope OR standalone without section context)
    allow_cover = typed_scope is TableScope.COVER or (
        effective_section is None and typed_scope is not TableScope.TOC
    )
    if allow_cover:
        res_reg = registration_table_template(source_grid)
        if res_reg:
            return TemplateResult(
                text=res_reg,
                bypass_guard=False,
                template_name="registration_table_template",
            )

        res_cover = cover_layout_template(
            source_grid, in_cover_scope=(typed_scope is TableScope.COVER)
        )
        if res_cover:
            return TemplateResult(
                text=res_cover, bypass_guard=True, template_name="cover_layout_template"
            )

        res_chk = checkbox_grid_template(source_grid)
        if res_chk:
            return TemplateResult(
                text=res_chk, bypass_guard=True, template_name="checkbox_grid_template"
            )

        if typed_scope is TableScope.COVER:
            res_single = single_row_horizontal_template(source_grid)
            if res_single:
                return TemplateResult(
                    text=res_single,
                    bypass_guard=True,
                    template_name="single_row_horizontal_template",
                )

    res_footnote = footnote_template(table, source_grid)
    if res_footnote:
        return TemplateResult(
            text=res_footnote, bypass_guard=True, template_name="footnote_template"
        )

    res_marked = marked_list_template(source_grid)
    if res_marked:
        return TemplateResult(
            text=res_marked, bypass_guard=True, template_name="marked_list_template"
        )

    res_exhibit = exhibit_index_template(source_grid, section_context=effective_section)
    if res_exhibit:
        return TemplateResult(
            text=res_exhibit, bypass_guard=True, template_name="exhibit_index_template"
        )

    # 2. Specialized statutory & family schedule templates
    res_shares = shares_purchased_template(
        source_grid, section_context=effective_section
    )
    if res_shares:
        return TemplateResult(
            text=res_shares,
            bypass_guard=False,
            template_name="shares_purchased_template",
        )

    res_titled_period = titled_period_table_template(source_grid)
    if res_titled_period:
        return TemplateResult(
            text=res_titled_period,
            bypass_guard=False,
            template_name="titled_period_table_template",
        )

    # 3. General financial & body table templates (side-by-side, uniform text)
    if typed_scope is not TableScope.TOC:
        res_product_status = sparse_status_matrix_template(source_grid)
        if res_product_status:
            return TemplateResult(
                text=res_product_status,
                bypass_guard=False,
                template_name="sparse_status_matrix_template",
            )

        res_side = side_by_side_template(table, source_grid)
        if res_side:
            return TemplateResult(
                text=res_side, bypass_guard=False, template_name="side_by_side_template"
            )

        res_uniform = uniform_text_table_template(source_grid)
        if res_uniform:
            return TemplateResult(
                text=res_uniform,
                bypass_guard=False,
                template_name="uniform_text_table_template",
            )

        res_two_col = two_column_prose_template(source_grid)
        if res_two_col:
            return TemplateResult(
                text=res_two_col,
                bypass_guard=True,
                template_name="two_column_prose_template",
            )

        res_definition = definition_table_template(source_grid)
        if res_definition:
            return TemplateResult(
                text=res_definition,
                bypass_guard=True,
                template_name="definition_table_template",
            )

    res_linked = linked_index_template(table, source_grid)
    if res_linked:
        return TemplateResult(
            text=res_linked, bypass_guard=True, template_name="linked_index_template"
        )

    return None


__all__ = ["TableScope", "apply_table_templates"]
