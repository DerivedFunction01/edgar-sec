"""Filing-catalog and document-storage settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .validators import validate_positive_int

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_TARGET_BYTES = 96 * 1024 * 1024


def get_catalog_specs() -> dict[str, dict[str, SettingSpec]]:
    from . import SettingSpec

    return {
        "documents": {
            "payload_target_bytes": SettingSpec(
                value_type=int,
                default=DEFAULT_TARGET_BYTES,
                env=True,
                machine_local=True,
                validate=validate_positive_int,
                description=(
                    "byte target a consolidated payload part is packed "
                    "towards during vacuum"
                ),
            ),
        },
    }


__all__ = [
    "DEFAULT_TARGET_BYTES",
    "get_catalog_specs",
]
