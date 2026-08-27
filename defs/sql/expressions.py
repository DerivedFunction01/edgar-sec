"""Expression AST nodes. One node per distinct expression shape."""

from __future__ import annotations

from dataclasses import dataclass

from .models import AggregateFunction, ArithmeticOp, Expr, Identifier, JsonPath


@dataclass(frozen=True, slots=True)
class Star(Expr):
    """The ``*`` projection or COUNT(*) argument."""


@dataclass(frozen=True, slots=True)
class Column(Expr):
    name: Identifier
    qualifier: Identifier | None = None


@dataclass(frozen=True, slots=True)
class Literal(Expr):
    """Inline literal (escaped at render time). For DDL contexts."""

    value: object


@dataclass(frozen=True, slots=True)
class Parameter(Expr):
    """A bound runtime value rendered as a positional placeholder."""

    value: object


@dataclass(frozen=True, slots=True)
class UnsafeExpression(Expr):
    """Raw SQL fragment; rejected unless the compiler allows unsafe nodes."""

    sql: str

    def __post_init__(self) -> None:
        if not isinstance(self.sql, str) or not self.sql.strip():
            raise ValueError("unsafe expression must be a non-empty string")


@dataclass(frozen=True, slots=True)
class Arithmetic(Expr):
    operator: ArithmeticOp
    terms: tuple[Expr, ...]

    def __post_init__(self) -> None:
        if len(self.terms) < 2:
            raise ValueError("arithmetic requires at least two terms")


@dataclass(frozen=True, slots=True)
class FunctionCall(Expr):
    function: str
    args: tuple[Expr, ...] = ()

    def __post_init__(self) -> None:
        if not self.function or not self.function.strip():
            raise ValueError("function name must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ScalarSubquery(Expr):
    query: object  # QueryExpr (relations), postponed to avoid cycles


@dataclass(frozen=True, slots=True)
class CaseBranch:
    when: object  # Condition
    then: Expr


@dataclass(frozen=True, slots=True)
class Case(Expr):
    branches: tuple[CaseBranch, ...]
    else_: Expr | None = None

    def __post_init__(self) -> None:
        if not self.branches:
            raise ValueError("case expression requires at least one branch")


@dataclass(frozen=True, slots=True)
class Aggregate(Expr):
    function: AggregateFunction
    argument: Expr | None = None

    def __post_init__(self) -> None:
        unary = {
            AggregateFunction.COUNT,
            AggregateFunction.SUM,
            AggregateFunction.AVG,
            AggregateFunction.MIN,
            AggregateFunction.MAX,
            AggregateFunction.COUNT_DISTINCT,
            AggregateFunction.STDDEV_SAMP,
            AggregateFunction.STDDEV_POP,
            AggregateFunction.VAR_SAMP,
            AggregateFunction.VAR_POP,
            AggregateFunction.MSE,
            AggregateFunction.RMSE,
            AggregateFunction.MAE,
            AggregateFunction.RANGE,
            AggregateFunction.MEDIAN,
            AggregateFunction.MODE,
        }
        if self.function in unary and self.argument is None:
            raise ValueError(f"{self.function.value} requires an argument")


@dataclass(frozen=True, slots=True)
class Windowed(Expr):
    operand: Expr
    partition_by: tuple[Expr, ...] = ()
    order_by: tuple[object, ...] = ()  # tuple[OrderBy]


@dataclass(frozen=True, slots=True)
class JsonExtract(Expr):
    target: Expr
    path: JsonPath


@dataclass(frozen=True, slots=True)
class Alias(Expr):
    """A projected or referenced expression with an output name."""

    expression: Expr
    name: str

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("alias name must be non-empty")


def col(name: str, qualifier: str | None = None) -> Column:
    """Convenience constructor: col('id', 'u') -> Column."""
    return Column(
        name=Identifier(name),
        qualifier=Identifier(qualifier) if qualifier else None,
    )


def excluded(name: str) -> Column:
    """Reference ``EXCLUDED.name`` inside ON CONFLICT DO UPDATE assignments."""
    return Column(name=Identifier(name), qualifier=Identifier("EXCLUDED"))


def param(value: object) -> Parameter:
    return Parameter(value)


def lit(value: object) -> Literal:
    return Literal(value)
