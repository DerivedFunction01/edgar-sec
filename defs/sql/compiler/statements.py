"""DML and execution statement rendering mixin for SQL AST compiler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..dialects import quote_ident, sql_literal
from ..errors import CapabilityError, ValidationError
from ..expressions import Expr, Literal, Parameter
from ..models import SqlDialect, Statement
from ..relations import Select, SetOperation
from ..schema import (
    CreateIndex,
    CreateTable,
    CreateView,
)
from ..statements import (
    AlterTable,
    Attach,
    Begin,
    Commit,
    CreateTrigger,
    Delete,
    Detach,
    DoNothing,
    DoUpdate,
    DropIndex,
    DropTable,
    DropTrigger,
    DropView,
    Explain,
    Grant,
    Insert,
    Pragma,
    Replace,
    Rollback,
    Savepoint,
    Truncate,
    UnsafeStatement,
    Update,
    ValuesSource,
)
from .common import _entered

if TYPE_CHECKING:
    from ..context import RenderContext


class StatementCompilerMixin:
    """Methods for rendering INSERT, UPDATE, DELETE, transactions, and utilities."""

    dialect: SqlDialect

    def _table(self, name: str) -> str:
        return ".".join(quote_ident(part) for part in name.split("."))

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
        if isinstance(stmt, Attach):
            if self.dialect is SqlDialect.POSTGRES:
                raise CapabilityError("ATTACH database", self.dialect.value)
            path_lit = sql_literal(stmt.path)
            alias_quoted = quote_ident(stmt.alias)
            if self.dialect is SqlDialect.SQLITE:
                return f"ATTACH DATABASE {path_lit} AS {alias_quoted}"
            ro_clause = ", READ_ONLY" if stmt.read_only else ""
            type_clause = f", TYPE {stmt.db_type.upper()}" if stmt.db_type else ""
            options = (
                f" ({type_clause.lstrip(', ')}{ro_clause})"
                if (type_clause or ro_clause)
                else ""
            )
            return f"ATTACH {path_lit} AS {alias_quoted}{options}"
        if isinstance(stmt, Detach):
            if self.dialect is SqlDialect.POSTGRES:
                raise CapabilityError("DETACH database", self.dialect.value)
            alias_quoted = quote_ident(stmt.alias)
            if self.dialect is SqlDialect.SQLITE:
                return f"DETACH DATABASE {alias_quoted}"
            return f"DETACH {alias_quoted}"
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


__all__ = ["StatementCompilerMixin"]
