"""Shared Parquet output defaults and settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .validators import validate_positive_int

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_ROW_GROUP_SIZE = 128_000
DEFAULT_PARQUET_READ_BATCH_SIZE = 65_536


def resolve_row_group_size(value: int | None = None) -> int:
    if value is not None:
        try:
            validate_positive_int(value)
        except ValueError as exc:
            raise ValueError("row_group_size must be positive") from exc
        return value
    from . import resolve_settings

    return int(resolve_settings(include=("parquet",))["parquet.row_group_size"])


def resolve_parquet_read_batch_size(value: int | None = None) -> int:
    if value is not None:
        try:
            validate_positive_int(value)
        except ValueError as exc:
            raise ValueError("batch_size must be positive") from exc
        return value
    from . import resolve_settings

    return int(resolve_settings(include=("parquet",))["parquet.read_batch_size"])


def get_parquet_specs() -> dict[str, dict[str, SettingSpec]]:
    from . import SettingSpec

    return {
        "parquet": {
            "row_group_size": SettingSpec(
                value_type=int,
                default=DEFAULT_ROW_GROUP_SIZE,
                env=True,
                cli=True,
                validate=validate_positive_int,
                description="maximum rows per Parquet row group",
            ),
            "read_batch_size": SettingSpec(
                value_type=int,
                default=DEFAULT_PARQUET_READ_BATCH_SIZE,
                env=True,
                machine_local=True,
                validate=validate_positive_int,
                description="rows read per Parquet batch when callers omit a size",
            ),
        },
    }


__all__ = [
    "DEFAULT_ROW_GROUP_SIZE",
    "DEFAULT_PARQUET_READ_BATCH_SIZE",
    "get_parquet_specs",
    "resolve_parquet_read_batch_size",
    "resolve_row_group_size",
]
