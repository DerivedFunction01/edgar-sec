"""Typed errors for AST validation and dialect capability failures."""

from __future__ import annotations


class SqlError(Exception):
    """Base class for all SQL contract violations."""


class ValidationError(SqlError):
    """An AST invariant was violated before rendering."""

    def __init__(self, message: str, *, path: str = "") -> None:
        self.path = path
        super().__init__(f"{path}: {message}" if path else message)


class ScopeError(ValidationError):
    """A column or CTE reference is outside the visible scope."""


class CapabilityError(SqlError):
    """The selected dialect does not support a requested feature."""

    def __init__(self, feature: str, dialect: str, detail: str = "") -> None:
        self.feature = feature
        self.dialect = dialect
        message = f"{dialect} does not support {feature}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class AstCycleError(ValidationError):
    """The AST contains an accidental Python object cycle."""


class AstDepthError(ValidationError):
    """The AST nesting exceeds the configured maximum depth."""
