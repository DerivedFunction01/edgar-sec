"""Shared compiler utilities, context managers, and function catalogs."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from typing import TYPE_CHECKING

from ..expressions import Literal, Parameter
from ..relations import Table

if TYPE_CHECKING:
    from ..context import RenderContext

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


__all__ = [
    "KNOWN_FUNCTIONS",
    "_contains_table_reference",
    "_entered",
]
