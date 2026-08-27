"""SQL AST compiler with recursive rendering and shared parameters."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields, is_dataclass
import json

from .context import RenderContext
from .dialects import policy_for, quote_ident, sql_literal
from .errors import CapabilityError, ValidationError
from .expressions import (
    Aggregate,
    Alias,
    Arithmetic,
    Case,
    Column,
    FunctionCall,
    JsonExtract,
    Literal,
    Parameter,
    ScalarSubquery,
    Star,
    UnsafeExpression,
    Windowed,
)
from .models import (
    AggregateFunction,
    ArithmeticOp,
    BooleanOp,
    ComparisonOp,
    CompiledQuery,
    Direction,
    Expr,
    MatchMode,
    QueryExpr,
    RangeOp,
    SqlDialect,
    Statement,
)
from .predicates import (
    BooleanGroup,
    Compare,
    Exists,
    JsonArrayContains,
    Membership,
    Not,
    NullTest,
    RangeTest,
    StringMatch,
    SubquerySource,
    ValueList,
)
from .relations import (
    CrossJoin,
    DerivedTable,
    Join,
    OrderBy,
    Select,
    SetOperation,
    Table,
)
from .schema import (
    Check,
    CheckConstraint,
    ColumnDef,
    ColumnType,
    CreateIndex,
    CreateTable,
    CreateView,
    DefaultCurrentTimestamp,
    DefaultExpression,
    DefaultValue,
    ExplicitNull,
    ForeignKey,
    IndexColumn,
    NotNull,
    PrimaryKey,
    PrimaryKeyConstraint,
    RawConstraint,
    References,
    Unique,
    UniqueConstraint,
)
from .statements import (
    AddColumn,
    AlterTable,
    Begin,
    Commit,
    CreateTrigger,
    Delete,
    DoNothing,
    DoUpdate,
    DropColumn,
    DropConstraint,
    DropIndex,
    DropTable,
    DropTrigger,
    DropView,
    Explain,
    Grant,
    Insert,
    Pragma,
    ReleaseSavepoint,
    Replace,
    Rollback,
    Savepoint,
    SelectSource,
    Truncate,
    Update,
    UnsafeStatement,
    ValuesSource,
)


KNOWN_FUNCTIONS = frozenset(
    {
        "year",
        "month",
        "day",
        "quarter",
        "date_diff",
        "epoch",
        "to_string",
        "to_number",
        "round",
        "ceil",
        "floor",
        "substring",
        "trim",
        "lower",
        "upper",
        "concat",
        "coalesce",
        "abs",
        "add",
        "subtract",
        "multiply",
        "divide",
        "modulo",
        "power",
        "sqrt",
        "starts_with",
        "ends_with",
        "str_contains",
        "length",
    }
)


def _contains_table_reference(
    node: object, name: str, seen: set[int] | None = None
) -> bool:
    """Find a relation reference without requiring a schema catalog."""
    if seen is None:
        seen = set()
    if id(node) in seen:
        return False
    seen.add(id(node))
    if isinstance(node, Table):
        return node.name == name
    if isinstance(node, (Parameter, Literal)):
        return False
    if is_dataclass(node):
        for field in fields(node):
            if _contains_table_reference(getattr(node, field.name), name, seen):
                return True
    elif isinstance(node, (tuple, list, frozenset)):
        return any(_contains_table_reference(item, name, seen) for item in node)
    return False


@contextmanager
def _entered(ctx: RenderContext, node: object):
    ctx.enter(node)
    try:
        yield
    finally:
        ctx.leave(node)


class QueryCompiler:
    def __init__(
        self,
        dialect: SqlDialect | str = SqlDialect.SQLITE,
        *,
        allow_unsafe: bool = False,
        max_ast_depth: int = 100,
    ) -> None:
        self.dialect = SqlDialect(dialect)
        self.policy = policy_for(self.dialect)
        self.allow_unsafe = allow_unsafe
        self.max_ast_depth = max_ast_depth

    def compile(self, statement: Statement) -> CompiledQuery:
        ctx = RenderContext(
            dialect=self.dialect,
            allow_unsafe=self.allow_unsafe,
            max_depth=self.max_ast_depth,
        )
        sql = self._statement(statement, ctx).rstrip(";")
        return CompiledQuery(sql=sql, params=tuple(ctx.params), dialect=self.dialect)

    def compile_ddl_batch(
        self, statements: tuple[Statement | CompiledQuery | str, ...]
    ) -> str:
        """Join already-rendered DDL statements without adding nesting semicolons."""
        rendered = []
        for statement in statements:
            if isinstance(statement, CompiledQuery):
                rendered.append(statement.sql.strip().rstrip(";"))
            elif isinstance(statement, str):
                rendered.append(statement.strip().rstrip(";"))
            else:
                rendered.append(self.compile(statement).sql)
        return "\n\n".join(item for item in rendered if item)

    def wrap_in_transaction(self, query: CompiledQuery | str) -> CompiledQuery | str:
        """Wrap a compiled statement or SQL string in BEGIN/COMMIT."""
        if isinstance(query, str):
            return f"BEGIN;\n{query.strip().rstrip(';')}\nCOMMIT;"
        return CompiledQuery(
            sql=f"BEGIN\n{query.sql.strip().rstrip(';')}\nCOMMIT",
            params=query.params,
            dialect=query.dialect or self.dialect,
        )

    # Expressions ---------------------------------------------------------

    def _expr(self, node, ctx: RenderContext) -> str:
        with _entered(ctx, node):
            if isinstance(node, Column):
                if node.qualifier is not None and ctx.scopes:
                    ctx.check_qualifier(node.qualifier.value)
                column = quote_ident(node.name.value)
                return (
                    f"{quote_ident(node.qualifier.value)}.{column}"
                    if node.qualifier is not None
                    else column
                )
            if isinstance(node, Star):
                return "*"
            if isinstance(node, Parameter):
                return ctx.add_param(node.value)
            if isinstance(node, Literal):
                return sql_literal(node.value)
            if isinstance(node, UnsafeExpression):
                self._unsafe(ctx)
                return node.sql
            if isinstance(node, Alias):
                return f"{self._expr(node.expression, ctx)} AS {quote_ident(node.name)}"
            if isinstance(node, Arithmetic):
                return (
                    "("
                    + f" {node.operator.value} ".join(
                        self._expr(term, ctx) for term in node.terms
                    )
                    + ")"
                )
            if isinstance(node, FunctionCall):
                name = node.function.lower()
                if name not in KNOWN_FUNCTIONS:
                    raise CapabilityError(
                        f"function {node.function}", self.dialect.value
                    )
                if name in {"starts_with", "ends_with", "str_contains"}:
                    return self._string_function(name, node.args, ctx)
                return self._function(name, [self._expr(arg, ctx) for arg in node.args])
            if isinstance(node, JsonExtract):
                target = self._expr(node.target, ctx)
                path = node.path.path
                if self.dialect is SqlDialect.POSTGRES:
                    if "." in path:
                        parts = ", ".join(
                            "'" + part.replace("'", "''") + "'"
                            for part in node.path.parts
                        )
                        return f"{target}::jsonb #>> ARRAY[{parts}]"
                    return f"{target}::jsonb ->> '{path.replace(chr(39), chr(39) * 2)}'"
                fn = (
                    "json_extract_string"
                    if self.dialect is SqlDialect.DUCKDB
                    else "json_extract"
                )
                safe_path = path.replace("'", "''")
                return f"{fn}({target}, '$.{safe_path}')"
            if isinstance(node, ScalarSubquery):
                return f"({self._query(node.query, ctx)})"
            if isinstance(node, Case):
                parts = []
                for branch in node.branches:
                    parts.append(
                        f"WHEN {self._condition(branch.when, ctx)} THEN {self._expr(branch.then, ctx)}"
                    )
                else_sql = (
                    f" ELSE {self._expr(node.else_, ctx)}"
                    if node.else_ is not None
                    else ""
                )
                return "(CASE " + " ".join(parts) + else_sql + " END)"
            if isinstance(node, Aggregate):
                return self._aggregate(node.function, node.argument, ctx)
            if isinstance(node, Windowed):
                operand = self._expr(node.operand, ctx)
                body = []
                if node.partition_by:
                    body.append(
                        "PARTITION BY "
                        + ", ".join(self._expr(x, ctx) for x in node.partition_by)
                    )
                if node.order_by:
                    body.append(
                        "ORDER BY "
                        + ", ".join(self._order(x, ctx) for x in node.order_by)
                    )
                return f"{operand} OVER ({' '.join(body)})"
            raise ValidationError(f"unsupported expression node: {type(node).__name__}")

    def _function(self, name: str, args: list[str]) -> str:
        arg0 = args[0] if args else "NULL"
        if name in {"trim", "lower", "upper", "abs", "sqrt", "length"}:
            return f"{name.upper()}({arg0})"
        if name == "concat":
            return (
                f"({' || '.join(args)})"
                if self.dialect is SqlDialect.SQLITE
                else f"CONCAT({', '.join(args)})"
            )
        if name == "coalesce":
            return f"COALESCE({', '.join(args)})"
        if name in {"add", "subtract", "multiply", "divide", "modulo"}:
            op = {
                "add": "+",
                "subtract": "-",
                "multiply": "*",
                "divide": "/",
                "modulo": "%",
            }[name]
            return "(" + f" {op} ".join(args) + ")"
        if name == "power":
            if len(args) < 2:
                raise ValidationError("power requires at least two arguments")
            result = args[-1]
            for base in reversed(args[:-1]):
                result = f"POWER({base}, {result})"
            return result
        if name == "ceil":
            return (
                f"CEIL({arg0})"
                if self.dialect is SqlDialect.SQLITE
                else f"CEILING({arg0})"
            )
        if name == "floor":
            return f"FLOOR({arg0})"
        if name in {"year", "month", "day", "quarter", "epoch"}:
            if self.dialect is SqlDialect.SQLITE:
                formats = {"year": "%Y", "month": "%m", "day": "%d", "epoch": "%s"}
                if name == "quarter":
                    return f"CAST((strftime('%m', {arg0}) + 2) / 3 AS INTEGER)"
                return f"CAST(strftime('{formats[name]}', {arg0}) AS INTEGER)"
            return f"EXTRACT({name.upper()} FROM CAST({arg0} AS TIMESTAMP))"
        if name == "date_diff":
            arg1 = args[1] if len(args) > 1 else "NULL"
            return (
                f"(julianday({arg1}) - julianday({arg0}))"
                if self.dialect is SqlDialect.SQLITE
                else f"DATE_PART('day', CAST({arg1} AS TIMESTAMP) - CAST({arg0} AS TIMESTAMP))"
            )
        if name == "to_string":
            return f"CAST({arg0} AS TEXT)"
        if name == "to_number":
            mode = "REAL" if self.dialect is SqlDialect.SQLITE else "NUMERIC"
            if len(args) > 1 and args[1].strip("'").lower() in {"int", "integer"}:
                mode = "INTEGER"
            return f"CAST({arg0} AS {mode})"
        if name == "round":
            if self.dialect is SqlDialect.SQLITE:
                return f"ROUND({arg0}, {args[1] if len(args) > 1 else '0'})"
            return (
                f"ROUND(CAST({arg0} AS NUMERIC), {args[1] if len(args) > 1 else '0'})"
            )
        if name == "substring":
            start = args[1] if len(args) > 1 else "0"
            return (
                f"SUBSTR({arg0}, ({start}) + 1{', ' + args[2] if len(args) > 2 else ''})"
                if self.dialect is SqlDialect.SQLITE
                else f"SUBSTRING({arg0} FROM ({start}) + 1{' FOR ' + args[2] if len(args) > 2 else ''})"
            )
        if name in {"starts_with", "ends_with", "str_contains"}:
            if len(args) < 2:
                return "1=1"
            patterns = args[1:]
            if name == "starts_with":
                pieces = [self._like_pattern(args[0], p, "prefix") for p in patterns]
                return "(" + " OR ".join(pieces) + ")"
            if name == "ends_with":
                pieces = [self._like_pattern(args[0], p, "suffix") for p in patterns]
                return "(" + " OR ".join(pieces) + ")"
            mode = "all"
            if patterns[-1].strip("'").lower() in {"any", "all"}:
                mode = patterns[-1].strip("'").lower()
                patterns = patterns[:-1]
            if not patterns:
                return "1=1"
            pieces = [self._like_pattern(args[0], p, "contains") for p in patterns]
            return "(" + (" OR " if mode == "any" else " AND ").join(pieces) + ")"
        raise CapabilityError(f"function {name}", self.dialect.value)

    def _like_pattern(
        self, value: str, pattern: str, mode: str, *, case_insensitive: bool = False
    ) -> str:
        operator = "LIKE"
        if case_insensitive and self.dialect is not SqlDialect.SQLITE:
            operator = "ILIKE"
        if self.dialect is SqlDialect.SQLITE:
            if mode == "prefix":
                return f"{value} {operator} {pattern} || '%'"
            if mode == "suffix":
                return f"{value} {operator} '%' || {pattern}"
            return f"{value} {operator} '%' || {pattern} || '%'"
        if mode == "prefix":
            return f"{value} {operator} CONCAT({pattern}, '%')"
        if mode == "suffix":
            return f"{value} {operator} CONCAT('%', {pattern})"
        return f"{value} {operator} CONCAT('%', {pattern}, '%')"

    def _string_function(
        self, name: str, args: tuple[object, ...], ctx: RenderContext
    ) -> str:
        if len(args) < 2:
            return "1=1"
        patterns = list(args[1:])
        mode = "all"
        if name == "str_contains" and isinstance(patterns[-1], Literal):
            candidate = str(patterns[-1].value).lower()
            if candidate in {"any", "all"}:
                mode = candidate
                patterns.pop()
        if not patterns:
            return "1=1"
        kind = {
            "starts_with": "prefix",
            "ends_with": "suffix",
            "str_contains": "contains",
        }[name]
        pieces = []
        for pattern in patterns:
            value_sql = self._expr(args[0], ctx)
            pattern_sql = self._expr(pattern, ctx)
            pieces.append(self._like_pattern(value_sql, pattern_sql, kind))
        joiner = " OR " if name != "str_contains" or mode == "any" else " AND "
        return "(" + joiner.join(pieces) + ")"

    def _aggregate(
        self, function: AggregateFunction, argument_node, ctx: RenderContext
    ) -> str:
        def argument() -> str:
            return self._expr(argument_node, ctx) if argument_node is not None else "*"

        if function is AggregateFunction.COUNT_DISTINCT:
            return f"COUNT(DISTINCT {argument()})"
        if function is AggregateFunction.MSE:
            return f"AVG(({argument()}) * ({argument()}))"
        if function is AggregateFunction.RMSE:
            return f"SQRT(AVG(({argument()}) * ({argument()})))"
        if function is AggregateFunction.MAE:
            return f"AVG(ABS({argument()}))"
        if function is AggregateFunction.RANGE:
            return f"(MAX({argument()}) - MIN({argument()}))"
        if function is AggregateFunction.MEDIAN:
            if self.dialect is SqlDialect.POSTGRES:
                return f"PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {argument()})"
            return f"MEDIAN({argument()})"
        if function is AggregateFunction.MODE:
            return (
                "MODE() WITHIN GROUP (ORDER BY " + argument() + ")"
                if self.dialect is SqlDialect.POSTGRES
                else f"MODE({argument()})"
            )
        if function in {
            AggregateFunction.STDDEV_SAMP,
            AggregateFunction.STDDEV_POP,
            AggregateFunction.VAR_SAMP,
            AggregateFunction.VAR_POP,
        }:
            if self.dialect is SqlDialect.SQLITE:

                def count() -> str:
                    return f"COUNT({argument()})"

                def sum_value() -> str:
                    return f"SUM({argument()})"

                def sum_square() -> str:
                    return f"SUM({argument()} * {argument()})"

                def numerator() -> str:
                    return f"({sum_square()} - ({sum_value()} * {sum_value()} * 1.0) / {count()})"

                def variance() -> str:
                    denominator = (
                        f"({count()} - 1)"
                        if function
                        in {AggregateFunction.STDDEV_SAMP, AggregateFunction.VAR_SAMP}
                        else count()
                    )
                    return f"({numerator()} / {denominator})"

                minimum = (
                    "1"
                    if function
                    in {AggregateFunction.STDDEV_SAMP, AggregateFunction.VAR_SAMP}
                    else "0"
                )
                value = (
                    f"SQRT({variance()})"
                    if function
                    in {AggregateFunction.STDDEV_SAMP, AggregateFunction.STDDEV_POP}
                    else variance()
                )
                return f"CASE WHEN {count()} > {minimum} THEN {value} ELSE NULL END"
        return f"{function.value.upper()}({argument()})"

    # Conditions ----------------------------------------------------------

    def _condition(self, node, ctx: RenderContext) -> str:
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

    # Queries -------------------------------------------------------------

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

    def _source(self, source, ctx: RenderContext) -> str:
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

    # Statements ----------------------------------------------------------

    def _statement(self, stmt: Statement, ctx: RenderContext) -> str:
        if isinstance(stmt, (Select, SetOperation)):
            return self._query(stmt, ctx)
        with _entered(ctx, stmt):
            return self._statement_inner(stmt, ctx)

    def _statement_inner(self, stmt: Statement, ctx: RenderContext) -> str:
        if isinstance(stmt, (Select, SetOperation)):
            return self._query(stmt, ctx)
        if isinstance(stmt, Insert):
            cols = ", ".join(quote_ident(x) for x in stmt.columns)
            if isinstance(stmt.source, ValuesSource):
                rows = []
                for row in stmt.source.rows:
                    rows.append(
                        "("
                        + ", ".join(
                            self._expr(
                                x
                                if isinstance(x, (Parameter, Literal, Expr))
                                else Parameter(x),
                                ctx,
                            )
                            for x in row
                        )
                        + ")"
                    )
                body = "VALUES " + ", ".join(rows)
            else:
                body = self._query(stmt.source.query, ctx)
            prefix = "INSERT"
            conflict = stmt.on_conflict
            if isinstance(conflict, DoNothing) and self.dialect is SqlDialect.SQLITE:
                prefix = "INSERT OR IGNORE"
            elif isinstance(conflict, Replace) and self.dialect is SqlDialect.SQLITE:
                prefix = "INSERT OR REPLACE"
            sql = f"{prefix} INTO {self._table(stmt.table)} ({cols})\n{body}"
            if (
                isinstance(conflict, DoNothing)
                and self.dialect is not SqlDialect.SQLITE
            ):
                target = (
                    f" ({', '.join(quote_ident(x) for x in conflict.target)})"
                    if conflict.target
                    else ""
                )
                sql += f"\nON CONFLICT{target} DO NOTHING"
            elif isinstance(conflict, DoUpdate):
                target = ", ".join(quote_ident(x) for x in conflict.target)
                assigns = ", ".join(
                    f"{quote_ident(k)} = {self._expr(v, ctx)}"
                    for k, v in conflict.assignments
                )
                sql += f"\nON CONFLICT ({target}) DO UPDATE SET {assigns}"
            elif (
                isinstance(conflict, Replace) and self.dialect is not SqlDialect.SQLITE
            ):
                if not conflict.target:
                    raise ValidationError(
                        "Replace requires target columns outside SQLite"
                    )
                target = ", ".join(quote_ident(x) for x in conflict.target)
                updates = [x for x in stmt.columns if x not in conflict.target]
                if updates:
                    assigns = ", ".join(
                        f"{quote_ident(x)} = EXCLUDED.{quote_ident(x)}" for x in updates
                    )
                    sql += f"\nON CONFLICT ({target}) DO UPDATE SET {assigns}"
                else:
                    sql += f"\nON CONFLICT ({target}) DO NOTHING"
            if stmt.returning:
                sql += "\nRETURNING " + ", ".join(
                    quote_ident(x) for x in stmt.returning
                )
            return sql
        if isinstance(stmt, Update):
            ctx.push_scope({stmt.table.split(".")[-1]}, allow_outer=True)
            try:
                assignments = ", ".join(
                    f"{quote_ident(k)} = {self._expr(v if isinstance(v, (Parameter, Literal, Expr)) else Parameter(v), ctx)}"
                    for k, v in stmt.assignments
                )
                sql = f"UPDATE {self._table(stmt.table)}\nSET {assignments}"
                if stmt.where is not None:
                    sql += "\nWHERE " + self._condition(stmt.where, ctx)
                if stmt.returning:
                    sql += "\nRETURNING " + ", ".join(
                        quote_ident(x) for x in stmt.returning
                    )
                return sql
            finally:
                ctx.pop_scope()
        if isinstance(stmt, Delete):
            ctx.push_scope({stmt.table.split(".")[-1]}, allow_outer=True)
            try:
                sql = f"DELETE FROM {self._table(stmt.table)}"
                if stmt.where is not None:
                    sql += "\nWHERE " + self._condition(stmt.where, ctx)
                if stmt.returning:
                    sql += "\nRETURNING " + ", ".join(
                        quote_ident(x) for x in stmt.returning
                    )
                return sql
            finally:
                ctx.pop_scope()
        if isinstance(stmt, CreateTable):
            with ctx.ddl():
                return self._create_table(stmt, ctx)
        if isinstance(stmt, CreateIndex):
            with ctx.ddl():
                cols = ", ".join(self._expr(x.expression, ctx) for x in stmt.columns)
                using = f" USING {stmt.using}" if stmt.using else ""
                sql = f"CREATE {'UNIQUE ' if stmt.unique else ''}INDEX {'IF NOT EXISTS ' if stmt.if_not_exists else ''}{quote_ident(stmt.name)} ON {self._table(stmt.table)}{using} ({cols})"
                if stmt.where is not None:
                    sql += " WHERE " + self._condition(stmt.where, ctx)
                return sql
        if isinstance(stmt, CreateView):
            with ctx.ddl():
                cols = (
                    f" ({', '.join(quote_ident(x) for x in stmt.columns)})"
                    if stmt.columns
                    else ""
                )
                return f"CREATE VIEW {'IF NOT EXISTS ' if stmt.if_not_exists else ''}{quote_ident(stmt.name)}{cols} AS\n{self._query(stmt.query, ctx)}"
        if isinstance(stmt, DropTable):
            return (
                f"DROP TABLE {'IF EXISTS ' if stmt.if_exists else ''}{self._table(stmt.table)}"
                + (
                    " CASCADE"
                    if stmt.cascade and self.dialect is SqlDialect.POSTGRES
                    else ""
                )
            )
        if isinstance(stmt, DropIndex):
            prefix = (
                f"{quote_ident(stmt.table)}."
                if stmt.table and self.dialect is SqlDialect.SQLITE
                else ""
            )
            return f"DROP INDEX {'IF EXISTS ' if stmt.if_exists else ''}{prefix}{quote_ident(stmt.name)}"
        if isinstance(stmt, DropView):
            return f"DROP VIEW {'IF EXISTS ' if stmt.if_exists else ''}{quote_ident(stmt.name)}"
        if isinstance(stmt, AlterTable):
            with ctx.ddl():
                return ";\n".join(
                    self._alter(stmt.table, action, ctx) for action in stmt.actions
                )
        if isinstance(stmt, Explain):
            prefix = (
                "EXPLAIN QUERY PLAN"
                if stmt.analyze and self.dialect is SqlDialect.SQLITE
                else ("EXPLAIN ANALYZE" if stmt.analyze else "EXPLAIN")
            )
            if stmt.verbose and self.dialect is not SqlDialect.SQLITE:
                prefix += " VERBOSE"
            return f"{prefix} {self._statement(stmt.query, ctx)}"
        if isinstance(stmt, Begin):
            return "BEGIN"
        if isinstance(stmt, Commit):
            return "COMMIT"
        if isinstance(stmt, Rollback):
            return "ROLLBACK" + (
                f" TO SAVEPOINT {quote_ident(stmt.savepoint)}" if stmt.savepoint else ""
            )
        if isinstance(stmt, Savepoint):
            return f"SAVEPOINT {quote_ident(stmt.name)}"
        if isinstance(stmt, ReleaseSavepoint):
            return f"RELEASE SAVEPOINT {quote_ident(stmt.name)}"
        if isinstance(stmt, Pragma):
            if self.dialect is SqlDialect.POSTGRES:
                raise CapabilityError("PRAGMA", self.dialect.value)
            return f"PRAGMA {stmt.name}" + (
                f" = {sql_literal(stmt.value)}" if stmt.value is not None else ""
            )
        if isinstance(stmt, Truncate):
            if self.dialect is SqlDialect.SQLITE:
                return f"DELETE FROM {self._table(stmt.table)}"
            return (
                f"TRUNCATE TABLE {self._table(stmt.table)}"
                + (
                    " RESTART IDENTITY"
                    if stmt.restart_identity and self.dialect is SqlDialect.POSTGRES
                    else ""
                )
                + (
                    " CASCADE"
                    if stmt.cascade and self.dialect is SqlDialect.POSTGRES
                    else ""
                )
            )
        if isinstance(stmt, Grant):
            return f"GRANT {', '.join(x.upper() for x in stmt.privileges)} ON {self._table(stmt.table)} TO {quote_ident(stmt.to_role)}"
        if isinstance(stmt, UnsafeStatement):
            self._unsafe(ctx)
            return stmt.sql
        if isinstance(stmt, (CreateTrigger, DropTrigger)):
            raise CapabilityError(
                type(stmt).__name__,
                self.dialect.value,
                "trigger renderer is not enabled yet",
            )
        raise ValidationError(f"unsupported statement node: {type(stmt).__name__}")

    def _table(self, name: str) -> str:
        return ".".join(quote_ident(part) for part in name.split("."))

    def _create_table(self, stmt: CreateTable, ctx: RenderContext) -> str:
        lines = [self._column(column, ctx) for column in stmt.columns]
        for constraint in stmt.constraints:
            if isinstance(constraint, PrimaryKeyConstraint):
                lines.append(
                    f"PRIMARY KEY ({', '.join(quote_ident(x) for x in constraint.columns)})"
                )
            elif isinstance(constraint, UniqueConstraint):
                lines.append(
                    f"UNIQUE ({', '.join(quote_ident(x) for x in constraint.columns)})"
                )
            elif isinstance(constraint, ForeignKey):
                line = f"FOREIGN KEY ({', '.join(quote_ident(x) for x in constraint.columns)}) REFERENCES {self._table(constraint.ref_table)} ({', '.join(quote_ident(x) for x in constraint.ref_columns)})"
                if constraint.on_delete:
                    line += f" ON DELETE {constraint.on_delete}"
                if constraint.on_update:
                    line += f" ON UPDATE {constraint.on_update}"
                lines.append(line)
            elif isinstance(constraint, CheckConstraint):
                lines.append(f"CHECK ({self._condition(constraint.condition, ctx)})")
        return f"CREATE TABLE {'IF NOT EXISTS ' if stmt.if_not_exists else ''}{self._table(stmt.table)} (\n  {',\n  '.join(lines)}\n)"

    def _column(self, column: ColumnDef, ctx: RenderContext) -> str:
        physical = self._column_type(column)
        parts = [quote_ident(column.name), physical]
        for constraint in column.constraints:
            if isinstance(constraint, PrimaryKey):
                parts.append(
                    "PRIMARY KEY"
                    + (
                        " AUTOINCREMENT"
                        if constraint.auto_increment
                        and self.dialect is SqlDialect.SQLITE
                        else ""
                    )
                )
            elif isinstance(constraint, NotNull):
                parts.append("NOT NULL")
            elif isinstance(constraint, ExplicitNull):
                parts.append("NULL")
            elif isinstance(constraint, Unique):
                parts.append("UNIQUE")
            elif isinstance(constraint, Check):
                parts.append(f"CHECK ({self._condition(constraint.condition, ctx)})")
            elif isinstance(constraint, DefaultCurrentTimestamp):
                parts.append("DEFAULT CURRENT_TIMESTAMP")
            elif isinstance(constraint, DefaultValue):
                parts.append(f"DEFAULT {sql_literal(constraint.value)}")
            elif isinstance(constraint, DefaultExpression):
                parts.append(f"DEFAULT {self._expr(constraint.expression, ctx)}")
            elif isinstance(constraint, References):
                text = f"REFERENCES {self._table(constraint.table)} ({', '.join(quote_ident(x) for x in constraint.columns)})"
                if constraint.on_delete:
                    text += f" ON DELETE {constraint.on_delete}"
                if constraint.on_update:
                    text += f" ON UPDATE {constraint.on_update}"
                parts.append(text)
            elif isinstance(constraint, RawConstraint):
                self._unsafe(ctx)
                parts.append(constraint.sql)
        return " ".join(parts)

    def _column_type(self, column: ColumnDef) -> str:
        if any(
            isinstance(x, PrimaryKey) and x.auto_increment for x in column.constraints
        ):
            return "SERIAL" if self.dialect is SqlDialect.POSTGRES else "INTEGER"
        types = {
            ColumnType.ID: "TEXT",
            ColumnType.TEXT: "TEXT",
            ColumnType.UUID: self.policy.uuid_type,
            ColumnType.JSON: self.policy.json_type,
            ColumnType.INT: "INTEGER",
            ColumnType.REAL: self.policy.real_type,
            ColumnType.BOOL: self.policy.bool_type,
            ColumnType.TIMESTAMP: self.policy.timestamp_type,
            ColumnType.BLOB: self.policy.blob_type,
        }
        return types.get(column.type, column.type)

    def _alter(self, table: str, action, ctx: RenderContext) -> str:
        prefix = f"ALTER TABLE {self._table(table)}"
        if isinstance(action, AddColumn):
            return f"{prefix} ADD COLUMN {self._column(action.column, ctx)}"
        if isinstance(action, DropColumn):
            return f"{prefix} DROP COLUMN {'IF EXISTS ' if action.if_exists and self.dialect is not SqlDialect.SQLITE else ''}{quote_ident(action.name)}"
        if isinstance(action, DropConstraint):
            if self.dialect is SqlDialect.SQLITE:
                raise CapabilityError("ALTER TABLE DROP CONSTRAINT", self.dialect.value)
            return f"{prefix} DROP CONSTRAINT {quote_ident(action.name)}" + (
                " CASCADE"
                if action.cascade and self.dialect is SqlDialect.POSTGRES
                else ""
            )
        raise ValidationError(f"unsupported ALTER action: {type(action).__name__}")

    def _unsafe(self, ctx: RenderContext) -> None:
        if not ctx.allow_unsafe:
            raise ValidationError(
                "unsafe SQL requires QueryCompiler(allow_unsafe=True)"
            )


from .relations import RecursiveCte  # noqa: E402  (needed by query renderer)
