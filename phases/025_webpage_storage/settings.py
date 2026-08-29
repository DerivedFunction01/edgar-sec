"""Phase-owned settings for raw webpage acquisition and storage."""

from __future__ import annotations

from defs.runtime.settings import SettingSpec

SETTING_SPECS = {
    "webpage_storage": {
        "zstd_level": SettingSpec(
            value_type=int,
            default=3,
            config=True,
            cli=True,
            description="zstandard compression level for raw document payloads",
        ),
        "mode": SettingSpec(
            value_type=str,
            default="fixture",
            config=True,
            cli=True,
            description="document acquisition mode: fixture or production",
        ),
    },
}

__all__ = ["SETTING_SPECS"]
