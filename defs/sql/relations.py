"""Query relations: SELECT, CTEs, FROM items, joins, ordering, set ops."""

from __future__ import annotations

from dataclasses import dataclass

from .expressions import Expr, Star
from .models import (
    AstNode,
    Condition,
    Direction,
    FromItem,
    JoinKind,
    NullsOrder,
    QueryExpr,
    SetOperator,
)


@dataclass(frozen=True, slots=True)
class Table(FromItem):
    name: str
    alias: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("table name must be non-empty")
        if self.alias is not None and not self.alias.strip():
            raise ValueError("table alias must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class DerivedTable(FromItem):
    query: QueryExpr
    alias: str

    def __post_init__(self) -> None:
        if not self.alias or not self.alias.strip():
            raise ValueError("derived table alias must be non-empty")


@dataclass(frozen=True, slots=True)
class OrderBy:
    expression: Expr
    direction: Direction = Direction.ASC
    nulls: NullsOrder | None = None


@dataclass(frozen=True, slots=True)
class Join(AstNode):
    kind: JoinKind
    source: FromItem
    condition: Condition


@dataclass(frozen=True, slots=True)
class CrossJoin(AstNode):
    source: FromItem


@dataclass(frozen=True, slots=True)
class Cte:
    name: str
    query: QueryExpr
    columns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("CTE name must be non-empty")


@dataclass(frozen=True, slots=True)
class RecursiveCte:
    name: str
    seed: QueryExpr
    recursive_term: QueryExpr
    operator: SetOperator = SetOperator.UNION_ALL
    columns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("recursive CTE name must be non-empty")
        if self.operator not in (SetOperator.UNION, SetOperator.UNION_ALL):
            raise ValueError(
                "recursive CTE requires UNION or UNION ALL between seed and recursive term"
            )


@dataclass(frozen=True, slots=True)
class WithClause:
    ctes: tuple[Cte | RecursiveCte, ...]

    @property
    def is_recursive(self) -> bool:
        return any(isinstance(cte, RecursiveCte) for cte in self.ctes)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(cte.name for cte in self.ctes)


@dataclass(frozen=True, slots=True)
class Select(QueryExpr):
    source: FromItem | None = None
    projection: tuple[Expr, ...] = (Star(),)
    with_: WithClause | None = None
    distinct: bool = False
    joins: tuple[Join | CrossJoin, ...] = ()
    where: Condition | None = None
    group_by: tuple[Expr, ...] = ()
    having: Condition | None = None
    order_by: tuple[OrderBy, ...] = ()
    limit: int | None = None
    offset: int | None = None

    def __post_init__(self) -> None:
        if not self.projection:
            raise ValueError("select projection must be non-empty; use Star()")
        if self.limit is not None and self.limit < 0:
            raise ValueError("limit must be >= 0")
        if self.offset is not None and self.offset < 0:
            raise ValueError("offset must be >= 0")


@dataclass(frozen=True, slots=True)
class SetOperation(QueryExpr):
    left: QueryExpr
    operator: SetOperator
    right: QueryExpr
    order_by: tuple[OrderBy, ...] = ()
    limit: int | None = None
    offset: int | None = None
