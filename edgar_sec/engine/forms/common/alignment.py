"""Form-schema column anchor alignment state machine for tabular SEC filings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CanonicalColumn:
    """Specification of a single canonical column within an SEC table schema."""

    index: int
    name: str
    is_required: bool = True
    is_anchor: bool = False
    anchor_validator: Callable[[str], bool] | None = None
    data_extractor: Callable[[str], Any] | None = None
    value_validator: Callable[[str], bool] | None = None


@dataclass(frozen=True, slots=True)
class TableSchema:
    """Ordered immutable collection of canonical column specifications."""

    name: str
    columns: tuple[CanonicalColumn, ...]
    anchor_columns: tuple[CanonicalColumn, ...] = ()

    def __post_init__(self) -> None:
        if not self.anchor_columns:
            object.__setattr__(
                self,
                "anchor_columns",
                tuple(c for c in self.columns if c.is_anchor and c.anchor_validator),
            )

    def get_column(self, index: int) -> CanonicalColumn:
        return self.columns[index]

    @property
    def total_columns(self) -> int:
        return len(self.columns)


@dataclass(frozen=True, slots=True)
class AnchorMatch:
    """Position of a strict anchor match binding a raw cell to a canonical column."""

    cell_index: int
    col_index: int
    extracted_value: Any


def find_strict_anchors(
    cells: tuple[str, ...],
    schema: TableSchema,
) -> list[AnchorMatch]:
    """Identify strict format anchors maintaining monotonic canonical ordering."""
    matches: list[AnchorMatch] = []
    used_cells: set[int] = set()

    for col in schema.anchor_columns:
        assert col.anchor_validator is not None
        for c_idx, cell in enumerate(cells):
            if c_idx in used_cells:
                continue
            if matches and c_idx <= matches[-1].cell_index:
                continue
            if col.anchor_validator(cell):
                val = col.data_extractor(cell) if col.data_extractor else cell
                matches.append(
                    AnchorMatch(
                        cell_index=c_idx,
                        col_index=col.index,
                        extracted_value=val,
                    )
                )
                used_cells.add(c_idx)
                break
    return matches


def _accepts(col: CanonicalColumn, cell: str) -> bool:
    """Report whether a cell may fill a canonical column."""
    if col.anchor_validator is not None and not col.anchor_validator(cell):
        return False
    if col.value_validator is not None and not col.value_validator(cell):
        return False
    return True


def _later_acceptor(cols: list[CanonicalColumn], index: int, cell: str) -> bool:
    """Report whether a later column's contract can hold a rejected value."""
    return any(
        later.value_validator is not None and later.value_validator(cell)
        for later in cols[index + 1 :]
    )


def _project_interval(
    interval_cells: list[tuple[int, str]],
    interval_cols: list[CanonicalColumn],
    result: dict[str, Any],
) -> bool:
    """Project intermediate cells to canonical columns using deficit logic.

    A value that breaks its column contract eliminates that reading; the value
    is still carried when no other column can hold it, so it stays as evidence.
    """
    if not interval_cols:
        return True

    if not interval_cells:
        for col in interval_cols:
            if col.is_required:
                return False
            result[col.name] = None
        return True

    if len(interval_cells) == len(interval_cols):
        paired = [
            (col, col.data_extractor(cell) if col.data_extractor else cell)
            for (_, cell), col in zip(interval_cells, interval_cols, strict=True)
            if col.value_validator is None or col.value_validator(cell)
        ]
        if len(paired) == len(interval_cols):
            for col, val in paired:
                result[col.name] = val
            return True

    req_cols = [c for c in interval_cols if c.is_required]
    opt_cols = [c for c in interval_cols if not c.is_required]

    if len(interval_cells) < len(req_cols):
        return False

    cell_idx = 0
    for col_index, col in enumerate(interval_cols):
        if cell_idx < len(interval_cells):
            _, cell = interval_cells[cell_idx]
            if col.anchor_validator is not None and not col.anchor_validator(cell):
                if col.is_required:
                    return False
                result[col.name] = None
                continue
            if col.value_validator is not None and not col.value_validator(cell):
                if _later_acceptor(interval_cols, col_index, cell):
                    if col.is_required:
                        return False
                    result[col.name] = None
                    continue
            val = col.data_extractor(cell) if col.data_extractor else cell
            if col.is_required or len(interval_cells) - cell_idx > len(req_cols):
                result[col.name] = val
                cell_idx += 1
                if col in req_cols:
                    req_cols.remove(col)
                continue
        result[col.name] = None
    return True


def align_row_to_schema(
    cells: tuple[str, ...],
    schema: TableSchema,
) -> dict[str, Any] | None:
    """Align raw row cells to canonical schema columns using anchor intervals."""
    clean_cells = [c.strip() for c in cells]
    indexed_cells = [(i, c) for i, c in enumerate(clean_cells) if c]
    if not indexed_cells:
        return None

    just_cells = tuple(c for _, c in indexed_cells)
    anchors = find_strict_anchors(just_cells, schema)

    result: dict[str, Any] = {}
    last_cell_idx = -1
    last_col_idx = -1

    for anchor in anchors:
        curr_cells = [
            (i, just_cells[i]) for i in range(last_cell_idx + 1, anchor.cell_index)
        ]
        curr_cols = [
            schema.get_column(i) for i in range(last_col_idx + 1, anchor.col_index)
        ]
        if not _project_interval(curr_cells, curr_cols, result):
            return None

        result[schema.get_column(anchor.col_index).name] = anchor.extracted_value
        last_cell_idx = anchor.cell_index
        last_col_idx = anchor.col_index

    trailing_cells = [
        (i, just_cells[i]) for i in range(last_cell_idx + 1, len(just_cells))
    ]
    trailing_cols = [
        schema.get_column(i) for i in range(last_col_idx + 1, schema.total_columns)
    ]
    if not _project_interval(trailing_cells, trailing_cols, result):
        return None

    for col in schema.columns:
        if col.name not in result:
            if col.is_required:
                return None
            result[col.name] = None

    return result


__all__ = [
    "AnchorMatch",
    "CanonicalColumn",
    "TableSchema",
    "align_row_to_schema",
    "find_strict_anchors",
]
