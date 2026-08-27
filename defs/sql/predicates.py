"""Predicate AST nodes. Each distinct predicate shape is its own variant."""

from __future__ import annotations

from dataclasses import dataclass

from .expressions import Expr, Parameter
from .models import BooleanOp, ComparisonOp, Condition, MatchMode, RangeOp


@dataclass(frozen=True, slots=True)
class Compare(Condition):
    left: Expr
    operator: ComparisonOp
    right: Expr


@dataclass(frozen=True, slots=True)
class ValueList:
    values: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class SubquerySource:
    query: object  # QueryExpr


@dataclass(frozen=True, slots=True)
class Membership(Condition):
    value: Expr
    source: ValueList | SubquerySource
    negated: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.source, ValueList) and not self.source.values:
            raise ValueError(
                "empty membership lists are rejected; render TRUE/FALSE explicitly"
            )


@dataclass(frozen=True, slots=True)
class RangeTest(Condition):
    value: Expr
    operator: RangeOp
    lower: Expr
    upper: Expr


@dataclass(frozen=True, slots=True)
class NullTest(Condition):
    value: Expr
    negated: bool = False


@dataclass(frozen=True, slots=True)
class Exists(Condition):
    query: object  # QueryExpr
    negated: bool = False


@dataclass(frozen=True, slots=True)
class StringMatch(Condition):
    value: Expr
    pattern: Expr
    mode: MatchMode = MatchMode.LIKE
    negated: bool = False
    case_insensitive: bool = False


@dataclass(frozen=True, slots=True)
class JsonArrayContains(Condition):
    """True when a JSON array column contains the bound member value."""

    target: Expr
    member: Parameter


@dataclass(frozen=True, slots=True)
class BooleanGroup(Condition):
    operator: BooleanOp
    terms: tuple[Condition, ...]

    @staticmethod
    def and_(*terms: Condition) -> BooleanGroup:
        return BooleanGroup(operator=BooleanOp.AND, terms=tuple(terms))

    @staticmethod
    def or_(*terms: Condition) -> BooleanGroup:
        return BooleanGroup(operator=BooleanOp.OR, terms=tuple(terms))


@dataclass(frozen=True, slots=True)
class Not(Condition):
    condition: Condition
