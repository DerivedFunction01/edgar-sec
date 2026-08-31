"""Typed table-scope contract for template dispatch.

The dispatcher in :mod:`defs.tables.templates` consumes a :class:`TableScope`
rather than an unvalidated string. The scope is a capability selector: it
describes which template families may activate for a given table. It is
deliberately form-name agnostic; SEC form families select scopes, they do not
branch inside the shared table layer.
"""

from __future__ import annotations

from enum import Enum


class TableScope(str, Enum):
    """Capability scope selecting which table templates may activate."""

    BODY = "body"
    TOC = "toc"
    COVER = "cover"

    @classmethod
    def from_string(cls, scope: str | TableScope) -> TableScope:
        """Coerce a legacy string or enum value into a typed scope."""
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
        """Return whether cover-specific templates may activate under this scope."""
        return self is TableScope.COVER

    @property
    def allows_body_templates(self) -> bool:
        """Return whether generic body templates may activate under this scope."""
        return self is not TableScope.TOC


def table_scope_from_string(scope: str | TableScope | None) -> TableScope:
    """Backwards-compatible coercion helper for callers passing plain strings."""
    return TableScope.from_string(scope)


__all__ = [
    "TableScope",
    "table_scope_from_string",
]
