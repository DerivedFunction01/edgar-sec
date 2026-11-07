"""Facade client cache settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .validators import validate_fraction, validate_positive_int

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_CONTENT_CACHE_FRACTION = 0.25
DEFAULT_CONTENT_DISK_BUDGET_BYTES = 2 * 1024 * 1024 * 1024


def get_client_specs() -> dict[str, dict[str, SettingSpec]]:
    from . import SettingSpec

    return {
        "client": {
            "content_cache_fraction": SettingSpec(
                value_type=float,
                default=DEFAULT_CONTENT_CACHE_FRACTION,
                env=True,
                machine_local=True,
                validate=validate_fraction,
                description=(
                    "fraction of one worker memory share budgeted to "
                    "a facade content cache"
                ),
            ),
            "content_disk_budget_bytes": SettingSpec(
                value_type=int,
                default=DEFAULT_CONTENT_DISK_BUDGET_BYTES,
                env=True,
                machine_local=True,
                validate=validate_positive_int,
                description="byte budget for the facade content cache disk tier",
            ),
        },
    }


__all__ = [
    "DEFAULT_CONTENT_CACHE_FRACTION",
    "DEFAULT_CONTENT_DISK_BUDGET_BYTES",
    "get_client_specs",
]
