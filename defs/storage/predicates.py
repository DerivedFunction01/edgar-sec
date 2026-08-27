"""Backend-neutral query/predicate model evaluated identically by every backend.

Predicates are simple frozen dataclasses with a shared ``field`` and an
``evaluate(record)`` implementation. SQL backends may compile the same shapes
into SQL pushdown; file backends evaluate them in memory via
:func:`evaluate_query`. The logical result must be identical either way.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from .errors import StorageError

# Predicates -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Eq:
    field: str
    value: Any

    def matches(self, record: dict) -> bool:
        return record.get(self.field) == self.value


@dataclass(frozen=True, slots=True)
class Neq:
    field: str
    value: Any

    def matches(self, record: dict) -> bool:
        return record.get(self.field) != self.value


@dataclass(frozen=True, slots=True)
class InSet:
    field: str
    values: tuple[Any, ...]

    def __init__(self, field: str, values: Iterable[Any]):
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "values", tuple(values))

    def matches(self, record: dict) -> bool:
        return record.get(self.field) in self.values


@dataclass(frozen=True, slots=True)
class IsNull:
    field: str

    def matches(self, record: dict) -> bool:
        return record.get(self.field) is None


@dataclass(frozen=True, slots=True)
class IsNotNull:
    field: str

    def matches(self, record: dict) -> bool:
        return record.get(self.field) is not None


@dataclass(frozen=True, slots=True)
class Between:
    field: str
    low: Any
    high: Any
    inclusive: bool = True

    def matches(self, record: dict) -> bool:
        value = record.get(self.field)
        if value is None or isinstance(value, bool):
            return False
        try:
            if self.inclusive:
                return self.low <= value <= self.high
            return self.low < value < self.high
        except TypeError:
            return False


@dataclass(frozen=True, slots=True)
class And:
    children: tuple[Any, ...]

    def __init__(self, *children: Any):
        object.__setattr__(self, "children", tuple(children))

    def matches(self, record: dict) -> bool:
        return all(_match(child, record) for child in self.children)


@dataclass(frozen=True, slots=True)
class Or:
    children: tuple[Any, ...]

    def __init__(self, *children: Any):
        object.__setattr__(self, "children", tuple(children))

    def matches(self, record: dict) -> bool:
        return any(_match(child, record) for child in self.children)


@dataclass(frozen=True, slots=True)
class Not:
    child: Any

    def matches(self, record: dict) -> bool:
        return not _match(self.child, record)


Predicate = Eq | Neq | InSet | IsNull | IsNotNull | Between | And | Or | Not


def _match(predicate: Predicate, record: dict) -> bool:
    return predicate.matches(record)


def predicate_fields(predicate: Predicate | None) -> set[str]:
    """Collect every top-level field referenced by a predicate tree."""
    if predicate is None:
        return set()
    if isinstance(predicate, (And, Or)):
        out: set[str] = set()
        for child in predicate.children:
            out |= predicate_fields(child)
        return out
    if isinstance(predicate, Not):
        return predicate_fields(predicate.child)
    return {predicate.field}


# Query plan -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SortKey:
    field: str
    descending: bool = False


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """Backend-neutral read/delete specification.

    ``columns=None`` means all fields. Field names are validated against the
    dataset spec before execution; nested paths are intentionally out of scope
    until an explicit list/struct contract exists.
    """

    columns: tuple[str, ...] | None = None
    predicates: tuple[Predicate, ...] = ()
    order_by: tuple[SortKey, ...] = ()
    limit: int | None = None

    def __post_init__(self) -> None:
        if self.columns is not None and not self.columns:
            raise StorageError(
                "query columns must be None for all-fields, or non-empty"
            )
        if self.limit is not None and self.limit < 0:
            raise StorageError("query limit must be >= 0")

    @staticmethod
    def for_keys(key_field: str, keys: Iterable[str]) -> QueryPlan:
        return QueryPlan(predicates=(InSet(key_field, keys),))


def conjunction(predicates: Iterable[Predicate]) -> Predicate | None:
    items = tuple(predicates)
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    return And(*items)


# Evaluation -----------------------------------------------------------------


def _sort_value(record: dict, key: str) -> tuple[int, Any]:
    value = record.get(key)
    # Stable total order: missing/None first, then typed values.
    if value is None:
        return (0, "")
    return (1, value)


def evaluate_query(records: Iterable[dict], plan: QueryPlan | None) -> Iterator[dict]:
    """Evaluate a query plan over in-memory records.

    Used directly by file backends and as the reference semantics that SQL
    backends must match when compiling predicates to SQL.
    """
    rows = list(records)
    if plan is not None:
        for predicate in plan.predicates:
            rows = [row for row in rows if _match(predicate, row)]
        for sort_key in reversed(plan.order_by):
            rows.sort(
                key=lambda row, f=sort_key.field: _sort_value(row, f),
                reverse=sort_key.descending,
            )
        if plan.limit is not None:
            rows = rows[: plan.limit]
    if plan is not None and plan.columns is not None:
        columns = tuple(plan.columns)
        for row in rows:
            yield {name: row.get(name) for name in columns}
    else:
        yield from rows
