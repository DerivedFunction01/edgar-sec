"""Filing-catalog settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import SettingSpec


def get_catalog_specs() -> dict[str, dict[str, SettingSpec]]:
    from . import SettingSpec

    return {}


__all__ = ["get_catalog_specs"]
