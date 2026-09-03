"""Specialized table layout templates and layout pattern dispatchers."""

from __future__ import annotations

from .common import TemplateResult, cell_lines, cell_text, row_aware_fallback, span_grid
from .cover import (
    checkbox_grid_template,
    cover_layout_template,
    single_row_horizontal_template,
)
from .dispatcher import TableScope, apply_table_templates
from .presentation import (
    bullet_list_template,
    side_by_side_template,
    signature_template,
    titled_period_table_template,
    uniform_text_table_template,
)
from .registration import registration_table_template

__all__ = [
    "TableScope",
    "TemplateResult",
    "apply_table_templates",
    "bullet_list_template",
    "cell_lines",
    "cell_text",
    "checkbox_grid_template",
    "cover_layout_template",
    "registration_table_template",
    "row_aware_fallback",
    "side_by_side_template",
    "signature_template",
    "single_row_horizontal_template",
    "span_grid",
    "titled_period_table_template",
    "uniform_text_table_template",
]
