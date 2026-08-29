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
DEFAULT_TARGET_FORMS: tuple[str, ...] = ()
DEFAULT_AMENDMENT = "both"


def default_config_path() -> Path:
    return resolve_paths("filing_extraction").config_path


@dataclass(frozen=True)
class Phase2Config:
    source_batch_size: int = DEFAULT_SOURCE_BATCH_SIZE
    target_forms: tuple[str, ...] = DEFAULT_TARGET_FORMS
    amendment: str = DEFAULT_AMENDMENT

    def __post_init__(self) -> None:
        if self.source_batch_size < 1:
            raise ValueError("source_batch_size must be >= 1")
        if self.amendment not in {"both", "original", "amendments"}:
            raise ValueError("amendment must be both, original, or amendments")
        normalized = tuple(f.strip().upper() for f in self.target_forms if f.strip())
        if normalized != self.target_forms:
            object.__setattr__(self, "target_forms", normalized)

    def resolved(self) -> Phase2Config:
        return self

    def to_dict(self) -> dict:
        value = self.resolved()
        return {
            "source_batch_size": value.source_batch_size,
            "target_forms": list(value.target_forms),
            "amendment": value.amendment,
        }

    @classmethod
    def from_dict(cls, value: dict) -> Phase2Config:
        allowed = {"source_batch_size", "target_forms", "amendment"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown Phase 02 config fields: {unknown}")
        data = dict(value)
        if "target_forms" in data:
            data["target_forms"] = tuple(data["target_forms"])
        return cls(**data).resolved()


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
    persisted_dict: dict = {}
    if config_path.exists():
        _version, value = read_json_config(
            config_path, expected_version=CONFIG_VERSION, payload_key="config"
        )
        persisted = Phase2Config.from_dict(value)
        persisted_dict = persisted.to_dict()

    settings_config: dict[str, object] = {}
    if persisted_dict.get("source_batch_size") is not None:
        settings_config["filing_extraction.source_batch_size"] = persisted_dict[
            "source_batch_size"
        ]
    target_forms = persisted_dict.get("target_forms") or []
    if target_forms:
        settings_config["filing_extraction.target_forms"] = ",".join(target_forms)
    if persisted_dict.get("amendment") is not None:
        settings_config["filing_extraction.amendment"] = persisted_dict["amendment"]

    resolved = resolve_settings(
        phase="filing_extraction",
        config=settings_config or None,
        env=env,
    )

    target_forms_raw = resolved.get("filing_extraction.target_forms", "")
    if isinstance(target_forms_raw, str):
        target_forms = tuple(
            f.strip().upper() for f in target_forms_raw.split(",") if f.strip()
        )
    elif isinstance(target_forms_raw, (list, tuple)):
        target_forms = tuple(
            str(f).strip().upper() for f in target_forms_raw if str(f).strip()
        )
    else:
        target_forms = DEFAULT_TARGET_FORMS

    return Phase2Config(
        source_batch_size=int(resolved["filing_extraction.source_batch_size"]),
        target_forms=target_forms,
        amendment=str(resolved.get("filing_extraction.amendment", DEFAULT_AMENDMENT)),
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
