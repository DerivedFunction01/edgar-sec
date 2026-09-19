"""Typed run options and configuration persistence for the metadata phase.

SEC transport settings (identity, pacing, retries, timeout, cache, failure
ledger) are owned by the shared settings registry and resolved through
``defs.sec_http.resolve_sec_transport_profile``; they are not phase options.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from defs.runtime.config_io import read_json_config, write_json_config
from defs.runtime.paths import resolve_paths
from defs.runtime.settings.runtime import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_PARTITION_COUNT,
)
from defs.storage import DEFAULT_STORAGE_FORMAT

DEFAULT_INPUT = "uploads/cik-sec.csv"
_DEFAULT_PATHS = resolve_paths("metadata", "default")
DEFAULT_ARTIFACTS = str(_DEFAULT_PATHS.run_root)
DEFAULT_PREVIEW_ARTIFACTS = str(_DEFAULT_PATHS.phase_paths.preview_root)

PROJECT_CONFIG_DEFAULT_PATH = str(_DEFAULT_PATHS.phase_paths.config_path)
CONFIG_VERSION = 2

PLAN_DEFINING_FIELDS = (
    "input_path",
    "artifacts_dir",
    "chunk_size",
    "partition_count",
    "limit",
    "storage_format",
    "source_manifest",
    "base_metadata_manifest",
    "augmentation",
)


@dataclass
class RunOptions:
    input_path: str = DEFAULT_INPUT
    artifacts_dir: str = DEFAULT_ARTIFACTS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    partition_count: int = DEFAULT_PARTITION_COUNT
    partition_id: int | None = None
    chunk_id: int | None = None
    threads: int | None = None
    limit: int | None = None
    run_id: str = "default"
    storage_format: str = DEFAULT_STORAGE_FORMAT
    source_manifest: str | None = None
    base_metadata_manifest: str | None = None
    augmentation: bool = False

    def validate(self) -> None:
        if self.threads is not None and self.threads < 1:
            raise ValueError("threads must be >= 1")
        if self.chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        if self.partition_count < 1:
            raise ValueError("partition_count must be >= 1")
        if self.storage_format not in {"parquet", "jsonl"}:
            raise ValueError("storage_format must be 'parquet' or 'jsonl'")
        if self.augmentation and not self.source_manifest:
            raise ValueError("augmentation requires --source-manifest")
        if self.augmentation and not self.base_metadata_manifest:
            raise ValueError("augmentation requires --base-metadata-manifest")

    def to_dict(self) -> dict:
        data = {
            "input_path": self.input_path,
            "artifacts_dir": self.artifacts_dir,
            "chunk_size": self.chunk_size,
            "partition_count": self.partition_count,
            "partition_id": self.partition_id,
            "limit": self.limit,
            "run_id": self.run_id,
            "storage_format": self.storage_format,
            "source_manifest": self.source_manifest,
            "base_metadata_manifest": self.base_metadata_manifest,
            "augmentation": self.augmentation,
        }
        if self.threads is not None:
            data["threads"] = self.threads
        return data

    def effective_threads(self) -> int:
        """Return an explicit thread override or the shared thread default."""
        if self.threads is not None:
            return self.threads
        from defs.runtime.resources import derive_resources

        return derive_resources().threads


def _supported_config_fields() -> dict[str, type]:
    return {
        "input_path": str,
        "artifacts_dir": str,
        "chunk_size": int,
        "partition_count": int,
        "limit": int,
        "storage_format": str,
    }


@dataclass
class ProjectConfig:
    input_path: str = DEFAULT_INPUT
    artifacts_dir: str = DEFAULT_ARTIFACTS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    partition_count: int = DEFAULT_PARTITION_COUNT
    limit: int | None = None
    storage_format: str = DEFAULT_STORAGE_FORMAT

    @classmethod
    def from_dict(cls, data: dict) -> ProjectConfig:
        if not any(
            section in data
            for section in ("dataset", "execution", "storage", "sec_http", "metadata")
        ):
            return cls._from_flat_dict(data)
        # Sections outside the supported set (including obsolete ones) are
        # ignored: shared settings own SEC transport and machine values.
        allowed_sections = {"dataset", "execution", "storage"}
        sections = {
            name: value for name, value in data.items() if name in allowed_sections
        }
        if any(not isinstance(value, dict) for value in sections.values()):
            raise ValueError("config sections must be JSON objects")
        flat = {}
        for section in sections.values():
            flat.update(section)
        if "format" in flat:
            flat["storage_format"] = flat.pop("format")
        return cls._from_flat_dict(flat)

    @classmethod
    def _from_flat_dict(cls, data: dict) -> ProjectConfig:
        supported = _supported_config_fields()
        kwargs = {}
        for key, value in data.items():
            if key not in supported:
                continue
            expected = supported[key]
            if value is None and expected is int:
                continue
            if not isinstance(value, expected):
                raise ValueError(
                    f"config field {key} must be {expected.__name__}, got {type(value).__name__}"
                )
            if key == "storage_format" and value not in {"parquet", "jsonl"}:
                raise ValueError("storage_format must be 'parquet' or 'jsonl'")
            kwargs[key] = value
        if "limit" not in kwargs:
            kwargs["limit"] = None
        return cls(**kwargs)

    def to_dict(self) -> dict:
        return {
            "dataset": {
                "input_path": self.input_path,
                "artifacts_dir": self.artifacts_dir,
                "limit": self.limit,
            },
            "execution": {
                "chunk_size": self.chunk_size,
                "partition_count": self.partition_count,
            },
            "storage": {"format": self.storage_format},
        }

    def validate(self) -> None:
        if self.chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        if self.partition_count < 1:
            raise ValueError("partition_count must be >= 1")
        if self.storage_format not in {"parquet", "jsonl"}:
            raise ValueError("storage_format must be 'parquet' or 'jsonl'")

    def to_run_options(self, **overrides) -> RunOptions:
        data = {
            "input_path": self.input_path,
            "artifacts_dir": self.artifacts_dir,
            "chunk_size": self.chunk_size,
            "partition_count": self.partition_count,
            "limit": self.limit,
            "storage_format": self.storage_format,
        }
        data.update(overrides)
        return RunOptions(**data)


def default_project_config() -> ProjectConfig:
    return ProjectConfig()


def write_project_config(path: str | Path, config: ProjectConfig) -> str:
    return write_json_config(
        path, config.to_dict(), version=CONFIG_VERSION, payload_key="config"
    )


def load_project_config(path: str | Path) -> ProjectConfig:
    _version, data = read_json_config(
        path, expected_version=CONFIG_VERSION, payload_key="config"
    )
    return ProjectConfig.from_dict(data)


def plan_defining_fields() -> tuple[str, ...]:
    return PLAN_DEFINING_FIELDS


def validate_plan_against_options(plan: dict, options: RunOptions) -> None:
    run_options = plan.get("run_options", {})
    for field_name in PLAN_DEFINING_FIELDS:
        default = False if field_name == "augmentation" else None
        expected = run_options.get(field_name, default)
        actual = getattr(options, field_name)
        if expected != actual:
            raise ValueError(
                f"plan was created with {field_name}='{expected}' but effective option is '{actual}'; "
                f"regenerate the plan with the current configuration"
            )


__all__ = [
    "CONFIG_VERSION",
    "DEFAULT_ARTIFACTS",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_INPUT",
    "DEFAULT_PREVIEW_ARTIFACTS",
    "DEFAULT_STORAGE_FORMAT",
    "PLAN_DEFINING_FIELDS",
    "PROJECT_CONFIG_DEFAULT_PATH",
    "ProjectConfig",
    "RunOptions",
    "default_project_config",
    "load_project_config",
    "plan_defining_fields",
    "validate_plan_against_options",
    "write_project_config",
]
