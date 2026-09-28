"""Artifact and cache path settings.

Logical paths are chosen so generated environment names match standard conventions:
artifacts.root -> ARTIFACTS_ROOT
cache.root -> CACHE_ROOT
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .validators import validate_non_negative_int

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_ARTIFACTS_ROOT = Path(".artifacts")
DEFAULT_CACHE_JSON_TTL_S = 90 * 24 * 60 * 60  # 90 days


def _cache_root(resolved: dict) -> Path:
    root = resolved.get("artifacts.root", DEFAULT_ARTIFACTS_ROOT)
    return Path(root) / "caches"


def get_paths_specs() -> dict[str, dict[str, SettingSpec]]:
    from . import SettingSpec

    return {
        "artifacts": {
            "root": SettingSpec(
                value_type=Path,
                default=DEFAULT_ARTIFACTS_ROOT,
                env=True,
                machine_local=True,
                description="shared generated-artifact workspace",
            ),
        },
        "cache": {
            "root": SettingSpec(
                value_type=Path,
                default=_cache_root,
                env=True,
                machine_local=True,
                description="HTTP response cache root",
            ),
            "json_ttl_s": SettingSpec(
                value_type=int,
                default=DEFAULT_CACHE_JSON_TTL_S,
                env=True,
                machine_local=True,
                validate=validate_non_negative_int,
                description="HTTP cache lifetime for mutable JSON URLs in seconds; zero means forever",
            ),
        },
    }


__all__ = [
    "DEFAULT_ARTIFACTS_ROOT",
    "DEFAULT_CACHE_JSON_TTL_S",
    "get_paths_specs",
]
