"""Snapshot DAG pagination and inspection settings.

``dag.page_size`` -> ``DAG_PAGE_SIZE``; ``dag.graph_limit`` -> ``DAG_GRAPH_LIMIT``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .validators import validate_positive_int

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_DAG_PAGE_SIZE = 15
DEFAULT_DAG_GRAPH_LIMIT = 25


def get_dag_specs() -> dict[str, dict[str, SettingSpec]]:
    """Return settings specifications for DAG interactive console."""
    from . import SettingSpec

    return {
        "dag": {
            "page_size": SettingSpec(
                value_type=int,
                default=DEFAULT_DAG_PAGE_SIZE,
                env=True,
                config=True,
                cli=True,
                validate=validate_positive_int,
                description="items per page in interactive DAG pick-lists",
            ),
            "graph_limit": SettingSpec(
                value_type=int,
                default=DEFAULT_DAG_GRAPH_LIMIT,
                env=True,
                config=True,
                cli=True,
                validate=validate_positive_int,
                description="nodes per page in interactive DAG swimlane viewer",
            ),
        },
    }


__all__ = [
    "DEFAULT_DAG_GRAPH_LIMIT",
    "DEFAULT_DAG_PAGE_SIZE",
    "get_dag_specs",
]
