"""Acquisition-specific response bound settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .validators import validate_positive_int

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_MAX_RESPONSE_BYTES = 268435456


def get_acquisition_specs() -> dict[str, dict[str, SettingSpec]]:
    from . import SettingSpec

    return {
        "acquisition": {
            "max_response_bytes": SettingSpec(
                value_type=int,
                default=DEFAULT_MAX_RESPONSE_BYTES,
                env=True,
                config=True,
                cli=True,
                validate=validate_positive_int,
                description="maximum decoded HTTP response body size in bytes",
            ),
        },
    }


__all__ = ["DEFAULT_MAX_RESPONSE_BYTES", "get_acquisition_specs"]
