"""Predicate and condition rendering mixin for SQL AST compiler."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ..errors import ValidationError
from ..expressions import Expr, Literal, Parameter
from ..models import BooleanOp, ComparisonOp, MatchMode, SqlDialect
from ..predicates import (
    BooleanGroup,
    Compare,
    Exists,
    JsonArrayContains,
    Membership,
    Not,
    NullTest,
    RangeTest,
    StringMatch,
    ValueList,
)
from .common import _entered

if TYPE_CHECKING:
    from ..context import RenderContext


class PredicateCompilerMixin:
    """Methods for rendering WHERE, HAVING, JOIN, and CHECK conditions."""

    dialect: SqlDialect

    def _condition(self, node: Any, ctx: RenderContext) -> str:
        if isinstance(node, Expr):
            return self._expr(node, ctx)
        with _entered(ctx, node):
            if isinstance(node, Compare):
                left = self._expr(node.left, ctx)
                right = self._expr(node.right, ctx)
                op = node.operator.value
                if (
                    node.operator is ComparisonOp.ILIKE
                    and self.dialect is SqlDialect.SQLITE
                ):
                    op = "LIKE"
                if (
                    node.operator is ComparisonOp.NOT_ILIKE
                    and self.dialect is SqlDialect.SQLITE
                ):
                    op = "NOT LIKE"
                if (
                    node.operator is ComparisonOp.IS_DISTINCT_FROM
                    and self.dialect is SqlDialect.SQLITE
                ):
                    op = "IS NOT"
                if (
                    node.operator is ComparisonOp.IS_NOT_DISTINCT_FROM
                    and self.dialect is SqlDialect.SQLITE
                ):
                    op = "IS"
                return f"{left} {op} {right}"
            if isinstance(node, Membership):
                left = self._expr(node.value, ctx)
                if isinstance(node.source, ValueList):
                    values = ", ".join(
                        self._expr(
                            v
                            if isinstance(v, (Parameter, Literal, Expr))
                            else Parameter(v),
                            ctx,
                        )
                        for v in node.source.values
                    )
                    right = f"({values})"
                else:
                    right = f"({self._query(node.source.query, ctx)})"
                return f"{left} {'NOT IN' if node.negated else 'IN'} {right}"
            if isinstance(node, RangeTest):
                return f"{self._expr(node.value, ctx)} {node.operator.value} {self._expr(node.lower, ctx)} AND {self._expr(node.upper, ctx)}"
            if isinstance(node, NullTest):
                return f"{self._expr(node.value, ctx)} IS {'NOT ' if node.negated else ''}NULL"
            if isinstance(node, Exists):
                return f"{'NOT ' if node.negated else ''}EXISTS ({self._query(node.query, ctx)})"
            if isinstance(node, StringMatch):
                value = self._expr(node.value, ctx)
                pattern = self._expr(node.pattern, ctx)
                if node.mode is MatchMode.LIKE:
                    op = "NOT LIKE" if node.negated else "LIKE"
                    if node.case_insensitive and self.dialect is not SqlDialect.SQLITE:
                        op = "NOT ILIKE" if node.negated else "ILIKE"
                    return f"{value} {op} {pattern}"
                body = self._like_pattern(
                    value,
                    pattern,
                    {
                        MatchMode.STARTS_WITH: "prefix",
                        MatchMode.ENDS_WITH: "suffix",
                        MatchMode.CONTAINS: "contains",
                    }[node.mode],
                    case_insensitive=node.case_insensitive,
                )
                return f"NOT ({body})" if node.negated else body
            if isinstance(node, JsonArrayContains):
                target = self._expr(node.target, ctx)
                if self.dialect is SqlDialect.POSTGRES:
                    return f"{target}::jsonb @> {ctx.add_param(json.dumps([node.member.value]))}::jsonb"
                return f"EXISTS (SELECT 1 FROM json_each({target}) WHERE value = {ctx.add_param(node.member.value)})"
            if isinstance(node, BooleanGroup):
                if not node.terms:
                    return "1=1" if node.operator is BooleanOp.AND else "1=0"
                return (
                    "("
                    + f" {node.operator.value} ".join(
                        self._condition(x, ctx) for x in node.terms
                    )
                    + ")"
                )
            if isinstance(node, Not):
                return f"NOT ({self._condition(node.condition, ctx)})"
            raise ValidationError(f"unsupported condition node: {type(node).__name__}")


__all__ = ["PredicateCompilerMixin"]
