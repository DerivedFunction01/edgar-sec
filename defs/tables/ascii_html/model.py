"""Core data models for ascii_html geometry-first table renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from defs.text.html import FastHtmlNode


class HorizontalAlign(str, Enum):
    """Horizontal text alignment."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"
    AUTO = "auto"


class VerticalAlign(str, Enum):
    """Vertical cell alignment."""

    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"
    BASELINE = "baseline"
    AUTO = "auto"


class BorderStyle(str, Enum):
    """Border stroke style."""

    NONE = "none"
    SOLID = "solid"
    DOUBLE = "double"
    DASHED = "dashed"
    DOTTED = "dotted"


@dataclass(frozen=True, slots=True)
class CellStyle:
    """Normalized inline style and presentation attributes for a cell or table."""

    width: float | None = None
    width_unit: str = "px"
    is_percent_width: bool = False
    height: float | None = None
    padding_left: float = 0.0
    padding_right: float = 0.0
    padding_top: float = 0.0
    padding_bottom: float = 0.0
    margin_left: float = 0.0
    margin_right: float = 0.0
    text_indent: float = 0.0
    text_align: HorizontalAlign = HorizontalAlign.AUTO
    vertical_align: VerticalAlign = VerticalAlign.AUTO
    white_space: str = "normal"
    font_weight: str = "normal"
    font_style: str = "normal"
    font_size: float | None = None
    background_color: str | None = None
    border_top_width: float = 0.0
    border_top_style: BorderStyle = BorderStyle.NONE
    border_top_color: str | None = None
    border_bottom_width: float = 0.0
    border_bottom_style: BorderStyle = BorderStyle.NONE
    border_bottom_color: str | None = None
    is_hidden: bool = False
    border_left_width: float = 0.0
    border_left_style: BorderStyle = BorderStyle.NONE
    border_left_color: str | None = None
    border_right_width: float = 0.0
    border_right_style: BorderStyle = BorderStyle.NONE
    border_right_color: str | None = None
    is_bold: bool = False
    is_italic: bool = False
    is_nowrap: bool = False


@dataclass(frozen=True, slots=True)
class SourceCell:
    """A cell extracted directly from source HTML before layout resolution."""

    row_index: int
    source_col_index: int
    tag: str
    text: str
    raw_attributes: dict[str, str] = field(default_factory=dict)
    style: CellStyle = field(default_factory=CellStyle)
    colspan: int = 1
    rowspan: int = 1
    is_nested_table_holder: bool = False
    nested_table_index: int | None = None
    indent_spaces: int = 0


@dataclass(frozen=True, slots=True)
class SourceTable:
    """A table extracted directly from source HTML DOM."""

    table_index: int
    parent_table_index: int | None = None
    raw_node: FastHtmlNode | None = None
    rows: tuple[tuple[SourceCell, ...], ...] = ()
    style: CellStyle = field(default_factory=CellStyle)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CellBox:
    """Estimated physical coordinate box for a cell."""

    left: float
    right: float
    top: float
    bottom: float
    confidence: float
    source_cell: SourceCell | None = None

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(0.0, self.bottom - self.top)


@dataclass(frozen=True, slots=True)
class BorderSegment:
    """A discrete border edge segment along a row boundary."""

    row: int
    start_column: int
    end_column: int
    edge: str  # "top" | "bottom" | "left" | "right"
    width: float = 1.0
    style: BorderStyle = BorderStyle.SOLID
    color: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class RenderBudget:
    """Table rendering width constraints and budgets."""

    max_table_width: int = 180
    max_column_width: int = 48
    max_text_column_width: int = 80
    minimum_numeric_width: int = 8
    column_spacing: int = 2


DEFAULT_RENDER_BUDGET = RenderBudget()


@dataclass(frozen=True, slots=True)
class TextLayoutDiagnostic:
    """Diagnostic generated during text wrapping or layout budget adjustments."""

    row: int
    column: int
    original_length: int
    rendered_lines: int
    forced_wrap: bool = False
    clipped: bool = False
    overflow: int = 0


@dataclass(frozen=True, slots=True)
class SpanGroup:
    """Multi-column or multi-row span ownership mapping."""

    start_row: int
    end_row: int
    start_col: int
    end_col: int
    source_cell: SourceCell


@dataclass(frozen=True, slots=True)
class ResolvedGrid:
    """Resolved 2D table grid with coordinate column assignments and layout metadata."""

    rows: tuple[tuple[str, ...], ...]
    column_alignments: tuple[HorizontalAlign, ...]
    column_widths: tuple[int, ...]
    header_row_count: int = 0
    header_divider_style: BorderStyle = BorderStyle.SOLID
    span_groups: tuple[SpanGroup, ...] = ()
    spacer_columns: tuple[int, ...] = ()
    border_segments: tuple[BorderSegment, ...] = ()
    confidence: float = 1.0
    diagnostics: tuple[TextLayoutDiagnostic, ...] = ()
    veto_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TableRenderResult:
    """Final output of ascii_html rendering."""

    ascii_text: str
    resolved_grid: ResolvedGrid
    confidence: float
    diagnostics: tuple[str, ...] = ()
    is_fallback_to_legacy: bool = False


__all__ = [
    "DEFAULT_RENDER_BUDGET",
    "BorderSegment",
    "BorderStyle",
    "CellBox",
    "CellStyle",
    "HorizontalAlign",
    "RenderBudget",
    "ResolvedGrid",
    "SourceCell",
    "SourceTable",
    "SpanGroup",
    "TableRenderResult",
    "TextLayoutDiagnostic",
    "VerticalAlign",
]
