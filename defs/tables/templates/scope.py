"""Typed table-scope contract for table classification.

The scope is a capability selector used by form and taxonomy context. It is
deliberately form-name agnostic; SEC form families select scopes, they do not
branch inside the shared geometry renderer.
"""

from __future__ import annotations

from enum import Enum


class TableScope(str, Enum):
    """Capability scope selecting which classification context applies."""

    BODY = "body"
    TOC = "toc"
    COVER = "cover"

    @classmethod
    def from_string(cls, scope: str | TableScope) -> TableScope:
        """Coerce a string or enum value into a typed scope."""
        if isinstance(scope, TableScope):
            return scope
        if scope is None:
            return cls.BODY
        normalized = scope.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        return cls.BODY

    @property
    def allows_cover_templates(self) -> bool:
        """Return whether cover-specific classification may activate."""
        return self is TableScope.COVER

    @property
    def allows_body_templates(self) -> bool:
        """Return whether body classification may activate under this scope."""
        return self is not TableScope.TOC


def table_scope_from_string(scope: str | TableScope | None) -> TableScope:
    """Coerce callers passing plain strings into the typed scope."""
    return TableScope.from_string(scope)


__all__ = [
    "TableScope",
    "table_scope_from_string",
]
