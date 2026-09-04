"""Declarative geometric shape constraints for table families."""

from __future__ import annotations

from dataclasses import dataclass

from defs.tables.tokens import is_numeric_cell


@dataclass(frozen=True, slots=True)
class ShapeConstraint:
    """Empirical geometric boundaries for a table family."""

    min_rows: int = 1
    max_rows: int = 1000
    max_rows_scoped: int | None = None
    min_cols: int = 1
    max_cols: int = 100
    min_numeric_density: float = 0.0
    max_numeric_density: float = 1.0
    max_avg_cell_chars: int = 250

    def effective_max_rows(self, is_authorized_scope: bool) -> int:
        """Return the maximum row ceiling, accounting for scope relaxation."""
        if is_authorized_scope and self.max_rows_scoped is not None:
            return self.max_rows_scoped
        return self.max_rows


def validate_shape(
    grid: list[list[str]],
    constraint: ShapeConstraint,
    *,
    in_scope: bool = False,
) -> tuple[bool, str]:
    """Validate a 2D table grid against a shape constraint."""
    if not grid:
        return False, "empty_grid"

    num_rows = len(grid)
    max_rows = constraint.effective_max_rows(in_scope)
    if num_rows < constraint.min_rows:
        return False, f"row_count_{num_rows}_below_min_{constraint.min_rows}"
    if num_rows > max_rows:
        return False, f"row_count_{num_rows}_exceeds_max_{max_rows}"

    col_counts = [len(row) for row in grid if row]
    max_cols = max(col_counts, default=0)
    if max_cols < constraint.min_cols:
        return False, f"col_count_{max_cols}_below_min_{constraint.min_cols}"
    if max_cols > constraint.max_cols:
        return False, f"col_count_{max_cols}_exceeds_max_{constraint.max_cols}"

    all_cells = [cell.strip() for row in grid for cell in row if cell.strip()]
    if not all_cells:
        return False, "all_cells_blank"

    avg_chars = sum(len(c) for c in all_cells) / len(all_cells)
    if avg_chars > constraint.max_avg_cell_chars:
        return (
            False,
            f"avg_cell_chars_{avg_chars:.1f}_exceeds_max_{constraint.max_avg_cell_chars}",
        )

    if constraint.min_numeric_density > 0.0 or constraint.max_numeric_density < 1.0:
        numeric_count = sum(1 for c in all_cells if is_numeric_cell(c))
        density = numeric_count / len(all_cells)
        if density < constraint.min_numeric_density:
            return (
                False,
                f"numeric_density_{density:.2f}_below_min_{constraint.min_numeric_density:.2f}",
            )
        if density > constraint.max_numeric_density:
            return (
                False,
                f"numeric_density_{density:.2f}_exceeds_max_{constraint.max_numeric_density:.2f}",
            )

    return True, ""
