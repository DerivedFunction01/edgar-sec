"""Relation, SELECT query, CTE, and set operation rendering mixin for SQL AST compiler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..dialects import quote_ident
from ..errors import ValidationError
from ..models import QueryExpr, SqlDialect
from ..relations import (
    CrossJoin,
    DerivedTable,
    OrderBy,
    RecursiveCte,
    Select,
    SetOperation,
    Table,
)
from .common import _contains_table_reference, _entered

if TYPE_CHECKING:
    from ..context import RenderContext


class RelationCompilerMixin:
    """Methods for rendering SELECT queries, joins, CTEs, and set operations."""

    dialect: SqlDialect

    def _query(self, query: QueryExpr, ctx: RenderContext) -> str:
        with _entered(ctx, query):
            if isinstance(query, SetOperation):
                sql = f"{self._query_operand(query.left, ctx)}\n{query.operator.value}\n{self._query_operand(query.right, ctx)}"
                if query.order_by:
                    sql += "\nORDER BY " + ", ".join(
                        self._order(x, ctx) for x in query.order_by
                    )
                if query.limit is not None:
                    sql += f"\nLIMIT {query.limit}"
                if query.offset is not None:
                    sql += f"\nOFFSET {query.offset}"
                return sql
            if not isinstance(query, Select):
                raise ValidationError(f"unsupported query node: {type(query).__name__}")
            prefix = ""
            if query.with_ is not None:
                if len(set(query.with_.names)) != len(query.with_.names):
                    raise ValidationError(
                        "CTE names must be unique within a WITH clause"
                    )
                ctes = []
                prior_ctes: set[str] = set()
                for cte in query.with_.ctes:
                    if isinstance(cte, RecursiveCte):
                        if _contains_table_reference(cte.seed, cte.name):
                            raise ValidationError(
                                f"recursive CTE seed cannot reference '{cte.name}'"
                            )
                        if not _contains_table_reference(cte.recursive_term, cte.name):
                            raise ValidationError(
                                f"recursive CTE term must reference '{cte.name}'"
                            )
                        bodies = (cte.seed, cte.recursive_term)
                        body_separator = f"\n{cte.operator.value}\n"
                    else:
                        if _contains_table_reference(cte.query, cte.name):
                            raise ValidationError(
                                f"self-referencing CTE '{cte.name}' must use RecursiveCte"
                            )
                        bodies = (cte.query,)
                        body_separator = ""
                    ctx.push_scope(prior_ctes, allow_outer=False)
                    try:
                        body = body_separator.join(
                            self._query(part, ctx) for part in bodies
                        )
                    finally:
                        ctx.pop_scope()
                    prior_ctes.add(cte.name)
                    cols = (
                        f" ({', '.join(quote_ident(x) for x in cte.columns)})"
                        if cte.columns
                        else ""
                    )
                    ctes.append(f"{quote_ident(cte.name)}{cols} AS (\n  {body}\n)")
                prefix = (
                    "WITH "
                    + ("RECURSIVE " if query.with_.is_recursive else "")
                    + ",\n".join(ctes)
                    + "\n"
                )
            aliases = self._aliases(query)
            ctx.push_scope(aliases, allow_outer=True)
            try:
                projection = ", ".join(self._expr(x, ctx) for x in query.projection)
                sql = (
                    prefix
                    + "SELECT "
                    + ("DISTINCT " if query.distinct else "")
                    + projection
                )
                if query.source is not None:
                    sql += "\nFROM " + self._source(query.source, ctx)
                for join in query.joins:
                    if isinstance(join, CrossJoin):
                        sql += "\nCROSS JOIN " + self._source(join.source, ctx)
                    else:
                        sql += f"\n{join.kind.value} {self._source(join.source, ctx)} ON {self._condition(join.condition, ctx)}"
                if query.where is not None:
                    sql += "\nWHERE " + self._condition(query.where, ctx)
                if query.group_by:
                    sql += "\nGROUP BY " + ", ".join(
                        self._expr(x, ctx) for x in query.group_by
                    )
                if query.having is not None:
                    sql += "\nHAVING " + self._condition(query.having, ctx)
                if query.order_by:
                    sql += "\nORDER BY " + ", ".join(
                        self._order(x, ctx) for x in query.order_by
                    )
                if query.limit is not None:
                    sql += f"\nLIMIT {query.limit}"
                if query.offset is not None:
                    sql += f"\nOFFSET {query.offset}"
                return sql
            finally:
                ctx.pop_scope()

    def _query_operand(self, query: QueryExpr, ctx: RenderContext) -> str:
        text = self._query(query, ctx)
        if isinstance(query, SetOperation):
            return f"({text})"
        if isinstance(query, Select) and (
            query.with_ is not None
            or query.order_by
            or query.limit is not None
            or query.offset is not None
        ):
            return f"({text})"
        return text

    def _aliases(self, query: Select) -> set[str]:
        names = []
        source = query.source
        if source is not None:
            if isinstance(source, Table):
                names.append(source.alias or source.name.split(".")[-1])
            elif isinstance(source, DerivedTable):
                names.append(source.alias)
        for join in query.joins:
            target = join.source
            if isinstance(target, Table):
                names.append(target.alias or target.name.split(".")[-1])
            elif isinstance(target, DerivedTable):
                names.append(target.alias)
        if any(not name for name in names):
            raise ValidationError("FROM and JOIN aliases must be non-empty")
        if len(set(names)) != len(names):
            raise ValidationError("FROM and JOIN aliases must be unique")
        return set(names)

    def _source(self, source: Any, ctx: RenderContext) -> str:
        if isinstance(source, Table):
            text = ".".join(quote_ident(part) for part in source.name.split("."))
            return f"{text} AS {quote_ident(source.alias)}" if source.alias else text
        if isinstance(source, DerivedTable):
            ctx.push_scope(set(), allow_outer=False)
            try:
                body = self._query(source.query, ctx)
            finally:
                ctx.pop_scope()
            return f"({body}) AS {quote_ident(source.alias)}"
        raise ValidationError(f"unsupported FROM node: {type(source).__name__}")

    def _order(self, order: OrderBy, ctx: RenderContext) -> str:
        text = f"{self._expr(order.expression, ctx)} {order.direction.value}"
        if order.nulls is not None:
            text += f" NULLS {order.nulls.value}"
        return text


__all__ = ["RelationCompilerMixin"]
