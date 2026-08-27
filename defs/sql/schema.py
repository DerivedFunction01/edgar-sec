"""DDL nodes: physical column types, constraints, tables, indexes, views."""

from __future__ import annotations

from dataclasses import dataclass

from .models import AstNode, Identifier


class ColumnType:
    """Logical column types with dialect-physical mapping (see compiler)."""

    ID = "id"
    UUID = "uuid"
    TEXT = "text"
    JSON = "json"
    INT = "int"
    REAL = "real"
    BOOL = "bool"
    TIMESTAMP = "timestamp"
    BLOB = "blob"


@dataclass(frozen=True, slots=True)
class ColumnConstraint(AstNode):
    pass


@dataclass(frozen=True, slots=True)
class PrimaryKey(ColumnConstraint):
    auto_increment: bool = False


@dataclass(frozen=True, slots=True)
class NotNull(ColumnConstraint):
    pass


@dataclass(frozen=True, slots=True)
class ExplicitNull(ColumnConstraint):
    """Preserves SQL sources that state NULL explicitly."""


@dataclass(frozen=True, slots=True)
class Unique(ColumnConstraint):
    pass


@dataclass(frozen=True, slots=True)
class Check(ColumnConstraint):
    condition: object  # Condition


@dataclass(frozen=True, slots=True)
class DefaultCurrentTimestamp(ColumnConstraint):
    pass


@dataclass(frozen=True, slots=True)
class DefaultValue(ColumnConstraint):
    value: object  # inline literal


@dataclass(frozen=True, slots=True)
class DefaultExpression(ColumnConstraint):
    expression: object  # Expr


@dataclass(frozen=True, slots=True)
class References(ColumnConstraint):
    table: str
    columns: tuple[str, ...]
    on_delete: str | None = None
    on_update: str | None = None


@dataclass(frozen=True, slots=True)
class RawConstraint(ColumnConstraint):
    sql: str


@dataclass(frozen=True, slots=True)
class ColumnDef(AstNode):
    name: str
    type: str
    constraints: tuple[ColumnConstraint, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("column name must be non-empty")
        if not self.type or not self.type.strip():
            raise ValueError("column type must be non-empty")


class TableConstraint(AstNode):
    pass


@dataclass(frozen=True, slots=True)
class PrimaryKeyConstraint(TableConstraint):
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.columns:
            raise ValueError("primary key requires at least one column")


@dataclass(frozen=True, slots=True)
class UniqueConstraint(TableConstraint):
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForeignKey(TableConstraint):
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]
    on_delete: str | None = None
    on_update: str | None = None


@dataclass(frozen=True, slots=True)
class CheckConstraint(TableConstraint):
    condition: object  # Condition


@dataclass(frozen=True, slots=True)
class CreateTable(AstNode):
    table: str
    columns: tuple[ColumnDef, ...]
    constraints: tuple[TableConstraint, ...] = ()
    if_not_exists: bool = True


@dataclass(frozen=True, slots=True)
class IndexColumn(AstNode):
    expression: object  # Expr; Identifier-backed Column renders quoted


@dataclass(frozen=True, slots=True)
class CreateIndex(AstNode):
    name: str
    table: str
    columns: tuple[IndexColumn, ...]
    unique: bool = False
    if_not_exists: bool = True
    using: str | None = None
    where: object | None = None  # Condition


@dataclass(frozen=True, slots=True)
class CreateView(AstNode):
    name: str
    query: object  # QueryExpr
    if_not_exists: bool = True
    columns: tuple[str, ...] = ()


def infer_sql_type(value: object) -> str:
    """Infer a logical column type from a Python value."""
    if isinstance(value, bool):
        return ColumnType.BOOL
    if isinstance(value, int):
        return ColumnType.INT
    if isinstance(value, float):
        return ColumnType.REAL
    if isinstance(value, (list, dict)):
        return ColumnType.JSON
    return ColumnType.TEXT
