"""Artifact and cache path settings.

The logical paths are chosen so generated environment names match the
long-standing documented names (``artifacts.root`` -> ``ARTIFACTS_ROOT``,
``cache.root`` -> ``CACHE_ROOT``).
``defs/runtime/paths.py`` resolves these when no explicit environment
mapping is supplied; an explicit mapping remains authoritative and never
consults the process dotenv file.
"""

from __future__ import annotations

from pathlib import Path

from . import SettingSpec


def _cache_root(resolved: dict) -> Path:
    root = resolved.get("artifacts.root", Path(".artifacts"))
    return Path(root) / "caches"


def _validate_non_negative_int(value: object) -> None:
    if int(value) < 0:
        raise ValueError("must be >= 0")


SETTING_SPECS = {
    "artifacts": {
        "root": SettingSpec(
            value_type=Path,
            default=Path(".artifacts"),
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
            default=90 * 24 * 60 * 60,
            env=True,
            machine_local=True,
            validate=_validate_non_negative_int,
            description="HTTP cache lifetime for mutable JSON URLs in seconds; zero means forever",
        ),
    },
}

__all__ = ["SETTING_SPECS"]
