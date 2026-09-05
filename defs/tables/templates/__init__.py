"""Table-scope capability contract used by form and taxonomy classification."""

from __future__ import annotations

from .scope import TableScope, table_scope_from_string

__all__ = [
    "TableScope",
    "table_scope_from_string",
]
