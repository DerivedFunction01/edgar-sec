"""Expression rendering mixin for SQL AST compiler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..dialects import quote_ident, sql_literal
from ..errors import CapabilityError, ValidationError
from ..expressions import (
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
from ..models import AggregateFunction, SqlDialect
from .common import KNOWN_FUNCTIONS, _entered

if TYPE_CHECKING:
    from ..context import RenderContext


class ExpressionCompilerMixin:
    """Methods for rendering expressions, functions, aggregates, and JSON operations."""

    dialect: SqlDialect

    def _expr(self, node: Any, ctx: RenderContext) -> str:
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
        self, function: AggregateFunction, argument_node: Any, ctx: RenderContext
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
        if (
            function
            in {
                AggregateFunction.STDDEV_SAMP,
                AggregateFunction.STDDEV_POP,
                AggregateFunction.VAR_SAMP,
                AggregateFunction.VAR_POP,
            }
            and self.dialect is SqlDialect.SQLITE
        ):

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


__all__ = ["ExpressionCompilerMixin"]
