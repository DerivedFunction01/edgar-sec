"""Shared SQL insertion-batch setting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .validators import validate_positive_int

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_SQL_INSERT_BATCH_SIZE = 1000


def resolve_sql_insert_batch_size(value: int | None = None) -> int:
    if value is not None:
        validate_positive_int(value)
        return value
    from . import resolve_settings

    return int(resolve_settings(include=("sql",))["sql.insert_batch_size"])


def get_sql_specs() -> dict[str, dict[str, SettingSpec]]:
    from . import SettingSpec

    return {
        "sql": {
            "insert_batch_size": SettingSpec(
                value_type=int,
                default=DEFAULT_SQL_INSERT_BATCH_SIZE,
                env=True,
                machine_local=True,
                validate=validate_positive_int,
                description="rows inserted per bounded SQL batch",
            ),
        },
    }


__all__ = [
    "DEFAULT_SQL_INSERT_BATCH_SIZE",
    "get_sql_specs",
    "resolve_sql_insert_batch_size",
]
