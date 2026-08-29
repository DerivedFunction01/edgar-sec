"""Typed run options and configuration persistence for the metadata phase."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from defs.runtime.config_io import read_json_config, write_json_config
from defs.runtime.paths import resolve_paths
from defs.runtime.settings import get_setting
from defs.runtime.settings.runtime import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_PARTITION_COUNT,
    DEFAULT_WORKERS,
)
from defs.sec_http import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RATE_LIMIT_RPS,
    DEFAULT_TIMEOUT_S,
    DEFAULT_USER_AGENT,
)
from defs.storage import DEFAULT_STORAGE_FORMAT

DEFAULT_INPUT = "uploads/cik-sec.csv"
_DEFAULT_PATHS = resolve_paths("metadata", "default")
DEFAULT_ARTIFACTS = str(_DEFAULT_PATHS.run_root)
DEFAULT_PREVIEW_ARTIFACTS = str(_DEFAULT_PATHS.phase_paths.preview_root)
DEFAULT_MAX_FAILURE_ATTEMPTS = 3

PROJECT_CONFIG_DEFAULT_PATH = str(_DEFAULT_PATHS.phase_paths.config_path)
CONFIG_VERSION = 2

PLAN_DEFINING_FIELDS = (
    "input_path",
    "artifacts_dir",
    "chunk_size",
    "partition_count",
    "limit",
    "storage_format",
)


def rate_limit_to_interval(requests_per_second: float) -> float:
    if requests_per_second <= 0:
        raise ValueError("rate_limit must be positive")
    return 1.0 / requests_per_second


def default_user_agent() -> str:
    setting = get_setting("sec.user_agent")
    return str(setting) if setting else DEFAULT_USER_AGENT


def default_cache_dir() -> str:
    return str(get_setting("cache.root"))


@dataclass
class RunOptions:
    input_path: str = DEFAULT_INPUT
    artifacts_dir: str = DEFAULT_ARTIFACTS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    partition_count: int = DEFAULT_PARTITION_COUNT
    partition_id: int | None = None
    chunk_id: int | None = None
    workers: int = DEFAULT_WORKERS
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES
    rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS
    user_agent: str = field(default_factory=default_user_agent)
    cache_dir: str = field(default_factory=default_cache_dir)
    max_failure_attempts: int = DEFAULT_MAX_FAILURE_ATTEMPTS
    ignore_failure_history: bool = False
    limit: int | None = None
    log_level: str = "INFO"
    run_id: str = "default"
    storage_format: str = DEFAULT_STORAGE_FORMAT

    def validate(self) -> None:
        if self.workers < 1:
            raise ValueError("workers must be >= 1")
        if self.chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        if self.partition_count < 1:
            raise ValueError("partition_count must be >= 1")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.max_failure_attempts < 0:
            raise ValueError("max_failure_attempts must be >= 0")
        if self.storage_format not in {"parquet", "jsonl"}:
            raise ValueError("storage_format must be 'parquet' or 'jsonl'")
        if not self.user_agent or "@" not in self.user_agent:
            raise ValueError(
                "SEC contact identity is required: set --user-agent or SEC_USER_AGENT to "
                "'AppName/1.0 your-email@example.com'"
            )

    def to_dict(self) -> dict:
        return {
            "input_path": self.input_path,
            "artifacts_dir": self.artifacts_dir,
            "chunk_size": self.chunk_size,
            "partition_count": self.partition_count,
            "partition_id": self.partition_id,
            "workers": self.workers,
            "timeout_s": self.timeout_s,
            "max_retries": self.max_retries,
            "rate_limit_rps": self.rate_limit_rps,
            "user_agent": self.user_agent,
            "cache_dir": self.cache_dir,
            "max_failure_attempts": self.max_failure_attempts,
            "ignore_failure_history": self.ignore_failure_history,
            "limit": self.limit,
            "log_level": self.log_level,
            "run_id": self.run_id,
            "storage_format": self.storage_format,
        }


def _supported_config_fields() -> dict[str, type]:
    return {
        "input_path": str,
        "artifacts_dir": str,
        "chunk_size": int,
        "partition_count": int,
        "workers": int,
        "timeout_s": float,
        "max_retries": int,
        "rate_limit_rps": float,
        "user_agent": str,
        "cache_dir": str,
        "max_failure_attempts": int,
        "limit": int,
        "storage_format": str,
    }


@dataclass
class ProjectConfig:
    input_path: str = DEFAULT_INPUT
    artifacts_dir: str = DEFAULT_ARTIFACTS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    partition_count: int = DEFAULT_PARTITION_COUNT
    workers: int = DEFAULT_WORKERS
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES
    rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS
    user_agent: str = field(default_factory=default_user_agent)
    cache_dir: str = field(default_factory=default_cache_dir)
    max_failure_attempts: int = DEFAULT_MAX_FAILURE_ATTEMPTS
    limit: int | None = None
    storage_format: str = DEFAULT_STORAGE_FORMAT

    @classmethod
    def from_dict(cls, data: dict) -> ProjectConfig:
        if not any(
            section in data
            for section in ("dataset", "execution", "storage", "sec_http", "metadata")
        ):
            return cls._from_flat_dict(data)
        allowed_sections = {
            "dataset",
            "execution",
            "storage",
            "sec_http",
            "metadata",
            "credentials",
        }
        unknown_sections = sorted(set(data) - allowed_sections)
        if unknown_sections:
            raise ValueError(f"unknown config sections: {unknown_sections}")
        sections = {name: value for name, value in data.items()}
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
        unknown = sorted(set(data) - set(_supported_config_fields()))
        if unknown:
            raise ValueError(f"unknown config fields: {unknown}")
        supported = _supported_config_fields()
        kwargs = {}
        for key, value in data.items():
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
                "workers": self.workers,
                "chunk_size": self.chunk_size,
                "partition_count": self.partition_count,
            },
            "storage": {"format": self.storage_format},
            "sec_http": {
                "timeout_s": self.timeout_s,
                "max_retries": self.max_retries,
                "rate_limit_rps": self.rate_limit_rps,
                "cache_dir": self.cache_dir,
            },
            "metadata": {"max_failure_attempts": self.max_failure_attempts},
        }

    def validate(self) -> None:
        if self.workers < 1:
            raise ValueError("workers must be >= 1")
        if self.chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        if self.partition_count < 1:
            raise ValueError("partition_count must be >= 1")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.max_failure_attempts < 0:
            raise ValueError("max_failure_attempts must be >= 0")
        if self.storage_format not in {"parquet", "jsonl"}:
            raise ValueError("storage_format must be 'parquet' or 'jsonl'")
        if not self.user_agent or "@" not in self.user_agent:
            raise ValueError(
                "SEC contact identity is required: set --user-agent or SEC_USER_AGENT to "
                "'AppName/1.0 your-email@example.com'"
            )

    def to_run_options(self, **overrides) -> RunOptions:
        data = {
            "input_path": self.input_path,
            "artifacts_dir": self.artifacts_dir,
            "chunk_size": self.chunk_size,
            "partition_count": self.partition_count,
            "workers": self.workers,
            "timeout_s": self.timeout_s,
            "max_retries": self.max_retries,
            "rate_limit_rps": self.rate_limit_rps,
            "user_agent": self.user_agent,
            "cache_dir": self.cache_dir,
            "max_failure_attempts": self.max_failure_attempts,
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
        expected = run_options.get(field_name)
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
    "DEFAULT_MAX_FAILURE_ATTEMPTS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_PREVIEW_ARTIFACTS",
    "DEFAULT_RATE_LIMIT_RPS",
    "DEFAULT_STORAGE_FORMAT",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_WORKERS",
    "PLAN_DEFINING_FIELDS",
    "PROJECT_CONFIG_DEFAULT_PATH",
    "ProjectConfig",
    "RunOptions",
    "default_cache_dir",
    "default_project_config",
    "default_user_agent",
    "load_project_config",
    "plan_defining_fields",
    "rate_limit_to_interval",
    "validate_plan_against_options",
    "write_project_config",
]
