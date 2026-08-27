"""Shared AST value objects, enums, marker bases, and result types.

Marker base classes live here so module-level node definitions can reference
one another without import cycles. All nodes are frozen, slotted dataclasses
holding tuples instead of mutable lists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SqlDialect(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    DUCKDB = "duckdb"


class StorageRuntime(StrEnum):
    OPFS = "opfs"


class ComparisonOp(StrEnum):
    EQ = "="
    NEQ = "!="
    GT = ">"
    GEQ = ">="
    LT = "<"
    LEQ = "<="
    LIKE = "LIKE"
    NOT_LIKE = "NOT LIKE"
    ILIKE = "ILIKE"
    NOT_ILIKE = "NOT ILIKE"
    IS_DISTINCT_FROM = "IS DISTINCT FROM"
    IS_NOT_DISTINCT_FROM = "IS NOT DISTINCT FROM"


class ArithmeticOp(StrEnum):
    ADD = "+"
    SUBTRACT = "-"
    MULTIPLY = "*"
    DIVIDE = "/"
    MODULO = "%"


class RangeOp(StrEnum):
    BETWEEN = "BETWEEN"
    NOT_BETWEEN = "NOT BETWEEN"


class BooleanOp(StrEnum):
    AND = "AND"
    OR = "OR"


class MatchMode(StrEnum):
    LIKE = "like"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    CONTAINS = "str_contains"


class AggregateFunction(StrEnum):
    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    COUNT_DISTINCT = "count_distinct"
    STDDEV_SAMP = "stddev_samp"
    STDDEV_POP = "stddev_pop"
    VAR_SAMP = "var_samp"
    VAR_POP = "var_pop"
    MSE = "mse"
    RMSE = "rmse"
    MAE = "mae"
    RANGE = "range"
    MEDIAN = "median"
    MODE = "mode"


class SetOperator(StrEnum):
    UNION = "UNION"
    UNION_ALL = "UNION ALL"
    INTERSECT = "INTERSECT"
    INTERSECT_ALL = "INTERSECT ALL"
    EXCEPT = "EXCEPT"
    EXCEPT_ALL = "EXCEPT ALL"


class Direction(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


class NullsOrder(StrEnum):
    FIRST = "FIRST"
    LAST = "LAST"


class JoinKind(StrEnum):
    INNER = "INNER JOIN"
    LEFT = "LEFT JOIN"
    RIGHT = "RIGHT JOIN"
    FULL = "FULL JOIN"


class TriggerTiming(StrEnum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    INSTEAD_OF = "INSTEAD OF"


class TriggerEvent(StrEnum):
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    UPDATE_OF = "UPDATE OF"


@dataclass(frozen=True, slots=True)
class Identifier:
    """A quoted SQL identifier. Validated to be non-empty."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("identifier must be a non-empty string")
        if "\x00" in self.value:
            raise ValueError("identifier must not contain NUL")


@dataclass(frozen=True, slots=True)
class QualifiedName:
    parts: tuple[Identifier, ...]

    def __post_init__(self) -> None:
        if not self.parts:
            raise ValueError("qualified name requires at least one part")

    @staticmethod
    def parse(value: str) -> QualifiedName:
        raw_parts = value.split(".")
        if any(not part.strip() for part in raw_parts):
            raise ValueError(f"invalid qualified name: {value!r}")
        return QualifiedName(tuple(Identifier(part.strip()) for part in raw_parts))

    @property
    def first(self) -> Identifier:
        return self.parts[0]


@dataclass(frozen=True, slots=True)
class JsonPath:
    """A dotted JSON path, e.g. ``nested.field``."""

    parts: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.parts:
            raise ValueError("json path must contain at least one part")
        for part in self.parts:
            if not part:
                raise ValueError("json path parts must be non-empty")
            if any(char in part for char in "'{}[],"):
                raise ValueError(
                    "json path part contains unsupported structural characters"
                )

    @staticmethod
    def parse(path: str) -> JsonPath:
        parts = tuple(path.split("."))
        return JsonPath(parts)

    @property
    def path(self) -> str:
        return ".".join(self.parts)


@dataclass(frozen=True, slots=True)
class CompiledQuery:
    sql: str
    params: tuple[object, ...]
    dialect: SqlDialect


# Marker base classes -------------------------------------------------------


class AstNode:
    """Base for every AST node; enables generic structural walks."""


class Expr(AstNode):
    """A scalar SQL expression."""


class Condition(AstNode):
    """A boolean SQL expression."""


class QueryExpr(AstNode):
    """A query usable at the top level or nested inside another query."""


class FromItem(AstNode):
    """A FROM/JOIN relation."""


class Statement(AstNode):
    """A top-level executable statement."""
