"""Specialized table layout templates and layout pattern dispatchers."""

from __future__ import annotations

from .common import (
    TemplateResult,
    cell_lines,
    cell_text,
    oriented_prose_fallback,
    row_aware_fallback,
    span_grid,
)
from .cover import (
    checkbox_grid_template,
    cover_layout_template,
    single_row_horizontal_template,
)
from .dispatcher import TableScope, apply_table_templates
from .exhibit_index import exhibit_index_template
from .fair_value import fair_value_template
from .maturities import maturity_schedule_template
from .presentation import (
    bullet_list_template,
    side_by_side_template,
    signature_template,
    titled_period_table_template,
    uniform_text_table_template,
)
from .registration import registration_table_template
from .shares_purchased import shares_purchased_template

__all__ = [
    "TableScope",
    "TemplateResult",
    "apply_table_templates",
    "bullet_list_template",
    "cell_lines",
    "cell_text",
    "checkbox_grid_template",
    "cover_layout_template",
    "exhibit_index_template",
    "fair_value_template",
    "maturity_schedule_template",
    "oriented_prose_fallback",
    "registration_table_template",
    "row_aware_fallback",
    "shares_purchased_template",
    "side_by_side_template",
    "signature_template",
    "single_row_horizontal_template",
    "span_grid",
    "titled_period_table_template",
    "uniform_text_table_template",
]
