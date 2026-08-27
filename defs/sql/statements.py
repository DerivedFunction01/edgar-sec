"""Statement AST nodes: DML, DDL wrappers, EXPLAIN, transactions, admin."""

from __future__ import annotations

from dataclasses import dataclass

from .expressions import Expr
from .models import (
    AstNode,
    Condition,
    QueryExpr,
    Statement,
    TriggerEvent,
    TriggerTiming,
)


# --- INSERT ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValuesSource(AstNode):
    rows: tuple[tuple[object, ...], ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("insert values requires at least one row")
        width = len(self.rows[0])
        for row in self.rows:
            if len(row) != width:
                raise ValueError("all insert rows must have the same column count")
        if width == 0:
            raise ValueError("insert rows must contain at least one value")


@dataclass(frozen=True, slots=True)
class SelectSource(AstNode):
    query: QueryExpr


@dataclass(frozen=True, slots=True)
class ConflictAction(AstNode):
    pass


@dataclass(frozen=True, slots=True)
class DoNothing(ConflictAction):
    target: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DoUpdate(ConflictAction):
    target: tuple[str, ...]
    assignments: tuple[tuple[str, Expr], ...]

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("DoUpdate requires conflict target columns")
        if not self.assignments:
            raise ValueError("DoUpdate requires at least one assignment")


@dataclass(frozen=True, slots=True)
class Replace(ConflictAction):
    """Delete-then-insert semantics (SQLite) or upsert (Postgres/DuckDB)."""

    target: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Insert(Statement):
    table: str
    columns: tuple[str, ...]
    source: ValuesSource | SelectSource
    on_conflict: ConflictAction | None = None
    returning: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.columns:
            raise ValueError("insert requires explicit target columns")


def insert_values(
    table: str,
    rows: list[dict] | dict,
    *,
    on_conflict: ConflictAction | None = None,
    returning: tuple[str, ...] = (),
) -> Insert:
    """Convenience constructor mapping dict rows into a validated Insert."""
    normalized = [rows] if isinstance(rows, dict) else list(rows)
    if not normalized:
        raise ValueError("insert_values requires at least one row")
    columns = tuple(normalized[0].keys())
    for index, row in enumerate(normalized):
        if tuple(row.keys()) != columns:
            raise ValueError(
                f"row {index} keys differ from first row; all rows must share keys"
            )
    source = ValuesSource(
        rows=tuple(tuple(row[c] for c in columns) for row in normalized)
    )
    return Insert(
        table=table,
        columns=columns,
        source=source,
        on_conflict=on_conflict,
        returning=returning,
    )


# --- UPDATE / DELETE --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Update(Statement):
    table: str
    assignments: tuple[tuple[str, Expr], ...]
    where: Condition | None = None
    returning: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.assignments:
            raise ValueError("update requires at least one assignment")

    @staticmethod
    def from_mapping(table: str, values: dict, **kw) -> "Update":
        if not values:
            raise ValueError("update requires at least one assignment")
        return Update(
            table=table,
            assignments=tuple(values.items()),
            **kw,
        )


@dataclass(frozen=True, slots=True)
class Delete(Statement):
    table: str
    where: Condition | None = None
    returning: tuple[str, ...] = ()


# --- DDL -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DropTable(Statement):
    table: str
    if_exists: bool = True
    cascade: bool = False


@dataclass(frozen=True, slots=True)
class DropIndex(Statement):
    name: str
    table: str | None = None
    if_exists: bool = True


@dataclass(frozen=True, slots=True)
class DropView(Statement):
    name: str
    if_exists: bool = True


@dataclass(frozen=True, slots=True)
class AddColumn(AstNode):
    column: object  # ColumnDef


@dataclass(frozen=True, slots=True)
class DropColumn(AstNode):
    name: str
    if_exists: bool = False


@dataclass(frozen=True, slots=True)
class DropConstraint(AstNode):
    name: str
    cascade: bool = False


@dataclass(frozen=True, slots=True)
class AlterTable(Statement):
    table: str
    actions: tuple[AddColumn | DropColumn | DropConstraint, ...]

    def __post_init__(self) -> None:
        if not self.actions:
            raise ValueError("alter table requires at least one action")


# --- EXPLAIN -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Explain(Statement):
    query: Statement | Insert | Update | Delete  # statement instances only
    analyze: bool = False
    verbose: bool = False


# --- TRANSACTIONS --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Begin(Statement):
    pass


@dataclass(frozen=True, slots=True)
class Commit(Statement):
    pass


@dataclass(frozen=True, slots=True)
class Rollback(Statement):
    savepoint: str | None = None


@dataclass(frozen=True, slots=True)
class Savepoint(Statement):
    name: str


@dataclass(frozen=True, slots=True)
class ReleaseSavepoint(Statement):
    name: str


# --- PRAGMA / TRUNCATE / GRANT ---------------------------------------------


@dataclass(frozen=True, slots=True)
class Pragma(Statement):
    name: str
    value: object | None = None


@dataclass(frozen=True, slots=True)
class Truncate(Statement):
    table: str
    restart_identity: bool = False
    cascade: bool = False


@dataclass(frozen=True, slots=True)
class Grant(Statement):
    privileges: tuple[str, ...]
    table: str
    to_role: str

    def __post_init__(self) -> None:
        allowed = {"SELECT", "INSERT", "UPDATE", "DELETE", "ALL"}
        for privilege in self.privileges:
            if privilege.upper() not in allowed:
                raise ValueError(f"unsupported privilege: {privilege}")


# --- TRIGGERS ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnsafeStatement(Statement):
    """Raw SQL statement escape hatch; requires allow_unsafe."""

    sql: str


@dataclass(frozen=True, slots=True)
class CreateTrigger(Statement):
    name: str
    timing: TriggerTiming
    events: tuple[TriggerEvent, ...]
    table: str
    body: tuple[Insert | Update | UnsafeStatement, ...]
    update_columns: tuple[str, ...] = ()
    if_not_exists: bool = True
    for_each_row: bool = True
    when_condition: Condition | None = None

    def __post_init__(self) -> None:
        if not self.events:
            raise ValueError("trigger requires at least one event")
        if TriggerEvent.UPDATE_OF in self.events and not self.update_columns:
            raise ValueError("UPDATE OF trigger requires update_columns")
        if not self.body:
            raise ValueError("trigger requires a body")


@dataclass(frozen=True, slots=True)
class DropTrigger(Statement):
    name: str
    table: str | None = None
    if_exists: bool = True
