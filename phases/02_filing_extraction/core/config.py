"""Persisted, machine-tunable options for bounded Phase 02 materialization."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from defs.runtime.config_io import read_json_config, write_json_config
from defs.runtime.paths import resolve_paths
from defs.runtime.settings import resolve_settings

CONFIG_VERSION = 1
DEFAULT_SOURCE_BATCH_SIZE = 1_000


def default_config_path() -> Path:
    return resolve_paths("filing_extraction").config_path


@dataclass(frozen=True)
class Phase2Config:
    source_batch_size: int = DEFAULT_SOURCE_BATCH_SIZE

    def __post_init__(self) -> None:
        if self.source_batch_size < 1:
            raise ValueError("source_batch_size must be >= 1")

    def resolved(self) -> Phase2Config:
        return self

    def to_dict(self) -> dict:
        value = self.resolved()
        return {"source_batch_size": value.source_batch_size}

    @classmethod
    def from_dict(cls, value: dict) -> Phase2Config:
        allowed = {"source_batch_size"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown Phase 02 config fields: {unknown}")
        return cls(**value).resolved()


def load(
    path: str | os.PathLike[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Phase2Config:
    """Load phase config, resolved through the settings registry.

    Precedence: environment (direct or canonical dotenv) overrides the
    persisted config file, which overrides the spec default. An explicit
    ``env`` mapping bypasses process/dotenv resolution for tests.
    """
    config_path = Path(path) if path is not None else default_config_path()
    persisted: Phase2Config | None = None
    if config_path.exists():
        _version, value = read_json_config(
            config_path, expected_version=CONFIG_VERSION, payload_key="config"
        )
        persisted = Phase2Config.from_dict(value)
    resolved = resolve_settings(
        phase="filing_extraction",
        config=(
            {}
            if persisted is None
            else {"filing_extraction.source_batch_size": persisted.source_batch_size}
        ),
        env=env,
    )
    return Phase2Config(
        source_batch_size=int(resolved["filing_extraction.source_batch_size"])
    )


def write(path: str | os.PathLike[str], config: Phase2Config) -> str:
    return write_json_config(
        path, config.to_dict(), version=CONFIG_VERSION, payload_key="config"
    )


__all__ = [
    "CONFIG_VERSION",
    "DEFAULT_SOURCE_BATCH_SIZE",
    "Phase2Config",
    "default_config_path",
    "load",
    "write",
]
