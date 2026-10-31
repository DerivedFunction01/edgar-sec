"""Snapshot DAG inspection settings.

``dag.graph_limit`` -> ``DAG_GRAPH_LIMIT``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .validators import validate_positive_int

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_DAG_GRAPH_LIMIT = 25


def get_dag_specs() -> dict[str, dict[str, SettingSpec]]:
    """Return settings specifications for DAG swimlane viewer."""
    from . import SettingSpec

    return {
        "dag": {
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
    "get_dag_specs",
]
