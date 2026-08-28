"""DDL and schema definition rendering mixin for SQL AST compiler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..dialects import quote_ident, sql_literal
from ..errors import CapabilityError, ValidationError
from ..models import SqlDialect
from ..schema import (
    Check,
    CheckConstraint,
    ColumnDef,
    ColumnType,
    CreateTable,
    DefaultCurrentTimestamp,
    DefaultExpression,
    DefaultValue,
    ExplicitNull,
    ForeignKey,
    NotNull,
    PrimaryKey,
    PrimaryKeyConstraint,
    RawConstraint,
    References,
    Unique,
    UniqueConstraint,
)
from ..statements import (
    AddColumn,
    DropColumn,
    DropConstraint,
)

if TYPE_CHECKING:
    from ..context import RenderContext
    from ..dialects import DialectPolicy


class DdlCompilerMixin:
    """Methods for rendering CREATE TABLE, column types, and ALTER TABLE actions."""

    dialect: SqlDialect
    policy: DialectPolicy

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

    def _alter(self, table: str, action: Any, ctx: RenderContext) -> str:
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


__all__ = ["DdlCompilerMixin"]
