"""Declarative geometric shape constraints for table families."""

from __future__ import annotations

from dataclasses import dataclass


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


__all__ = ["ShapeConstraint"]
