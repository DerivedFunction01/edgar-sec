"""Typed settings registry: spec model, collection, resolution, and rendering.

A setting's identity is its logical dotted path (e.g. ``runtime.threads``); the environment
name is derived from that path, never hand-written. Resolution flows through
:mod:`edgar_sec.foundation.runtime.env`.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ..env import get_env
from .catalog import get_catalog_specs
from .dag import get_dag_specs
from .paths import get_paths_specs
from .runtime import get_runtime_specs
from .sec import SecSettings, get_sec_specs

MISSING = object()
_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """One logical setting specification."""

    value_type: type = str
    default: object = ""
    env: bool = False
    config: bool = False
    cli: bool = False
    secret: bool = False
    machine_local: bool = False
    description: str = ""
    validate: Callable[[object], None] | None = None


def environment_name(logical_path: str) -> str:
    """Derive the environment name for a logical dotted path.

    ``sec.rate_limit_rps`` becomes ``SEC_RATE_LIMIT_RPS``; hyphens map to underscores.
    """
    if not logical_path or not isinstance(logical_path, str):
        raise ValueError(f"invalid setting path: {logical_path!r}")
    return logical_path.replace("-", "_").replace(".", "_").upper()


def _flatten_group(
    group: Mapping[str, object], prefix: str, out: dict[str, SettingSpec]
) -> None:
    for name, value in group.items():
        if not isinstance(name, str) or not _SEGMENT_RE.fullmatch(name):
            raise ValueError(f"invalid setting name {name!r} under {prefix!r}")
        path = f"{prefix}.{name}" if prefix else name
        if isinstance(value, Mapping):
            _flatten_group(value, path, out)
        elif isinstance(value, SettingSpec):
            if path in out:
                raise ValueError(f"duplicate setting path {path!r}")
            out[path] = value
        else:
            raise TypeError(f"malformed setting spec at {path!r}")


def collect_specs() -> dict[str, SettingSpec]:
    """Collect all shared setting specifications."""
    specs: dict[str, SettingSpec] = {}
    for spec_provider in (
        get_runtime_specs,
        get_paths_specs,
        get_sec_specs,
        get_catalog_specs,
        get_dag_specs,
    ):
        group = spec_provider()
        _flatten_group(group, "", specs)
    return specs


def _parse_value(spec: SettingSpec, path: str, raw: str) -> object:
    if spec.value_type is bool:
        text = raw.strip().lower()
        if text in _TRUE_VALUES:
            return True
        if text in _FALSE_VALUES:
            return False
        raise ValueError(f"setting {path!r} expects a boolean, got {raw!r}")
    try:
        if spec.value_type is int:
            return int(raw)
        if spec.value_type is float:
            return float(raw)
        if spec.value_type is Path:
            return Path(raw).expanduser()
    except ValueError as exc:
        raise ValueError(
            f"setting {path!r} expects {spec.value_type.__name__}, got {raw!r}"
        ) from exc
    return raw


def _check_typed_value(spec: SettingSpec, path: str, value: object) -> object:
    expected = spec.value_type
    if expected is Path:
        if isinstance(value, str):
            return Path(value).expanduser()
        if isinstance(value, Path):
            return value
    elif expected is int:
        if not isinstance(value, bool) and isinstance(value, int):
            return value
    elif expected is float:
        if not isinstance(value, bool) and isinstance(value, (int, float)):
            return float(value)
    elif expected is bool:
        if isinstance(value, bool):
            return value
    elif isinstance(value, str):
        return value
    raise ValueError(
        f"setting {path!r} expects {expected.__name__}, got {type(value).__name__}"
    )


def _env_raw_value(
    path: str, env: Mapping[str, str] | None, dotenv_path: Path | None = None
) -> object:
    name = environment_name(path)
    if env is not None:
        return env.get(name, MISSING)
    return get_env(name, default=MISSING, dotenv_path=dotenv_path)


def _call_default(default: Callable, resolved: Mapping[str, object]) -> object:
    try:
        parameter_count = len(inspect.signature(default).parameters)
    except (TypeError, ValueError):
        parameter_count = 0
    if parameter_count >= 1:
        return default(resolved)
    return default()


def _included(path: str, include: Iterable[str]) -> bool:
    for prefix in include:
        if path == prefix or path.startswith(f"{prefix}."):
            return True
    return False


def resolve_settings(
    config: Mapping[str, object] | None = None,
    cli_overrides: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    include: Iterable[str] | None = None,
    fallbacks: Mapping[str, object] | None = None,
    dotenv_path: Path | None = None,
) -> dict[str, object]:
    """Resolve settings to typed values with full hierarchy precedence.

    Precedence: CLI override -> env/dotenv -> persisted config -> default/factory.
    """
    specs = collect_specs()
    if include is not None:
        include_tuple = tuple(include)
        specs = {p: s for p, s in specs.items() if _included(p, include_tuple)}
    resolved: dict[str, object] = {}
    for path, spec in specs.items():
        value: object = MISSING
        if cli_overrides is not None and cli_overrides.get(path) is not None:
            value = _check_typed_value(spec, path, cli_overrides[path])
        elif spec.env:
            raw = _env_raw_value(path, env, dotenv_path=dotenv_path)
            if raw is not MISSING and raw != "":
                value = _parse_value(spec, path, str(raw))
        if (
            value is MISSING
            and spec.config
            and config is not None
            and config.get(path) is not None
        ):
            value = _check_typed_value(spec, path, config[path])
        if value is MISSING:
            default = spec.default
            if callable(default):
                value = _call_default(default, resolved)
            elif default is MISSING:
                value = (fallbacks or {}).get(path, MISSING)
            else:
                value = default
        if value is MISSING:
            raise ValueError(f"setting {path!r} has no value")
        if spec.validate is not None:
            try:
                spec.validate(value)
            except ValueError as exc:
                raise ValueError(f"invalid value for setting {path!r}: {exc}") from exc
        resolved[path] = value
    return resolved


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Convenience typed object wrapping resolved configuration values."""

    sec: SecSettings
    worker_memory_mib: int
    worker_memory_safety: float
    memory_fraction: float
    default_chunk_size: int
    artifacts_root: Path
    cache_root: Path
    ttl_s: int
    temp_directory: Path | None
    log_level: str = "INFO"


def resolve_runtime_settings(
    config: Mapping[str, object] | None = None,
    cli_overrides: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> RuntimeSettings:
    """Resolve settings and return a structured RuntimeSettings model."""
    raw = resolve_settings(
        config=config,
        cli_overrides=cli_overrides,
        env=env,
        dotenv_path=dotenv_path,
    )
    sec = SecSettings(
        user_agent=str(raw["sec.user_agent"]),
        rate_limit_rps=float(raw["sec.rate_limit_rps"]),
        timeout_s=float(raw["sec.timeout_s"]),
        max_retries=int(raw["sec.max_retries"]),
        max_failure_attempts=int(raw["sec.max_failure_attempts"]),
    )
    temp_dir_val = raw.get("runtime.temp_directory")
    temp_dir = Path(str(temp_dir_val)) if temp_dir_val else None

    return RuntimeSettings(
        sec=sec,
        worker_memory_mib=int(raw["runtime.worker_memory_mib"]),
        worker_memory_safety=float(raw["runtime.worker_memory_safety"]),
        memory_fraction=float(raw["runtime.memory_fraction"]),
        default_chunk_size=int(raw["runtime.chunk_size"]),
        artifacts_root=Path(str(raw["artifacts.root"])),
        cache_root=Path(str(raw["cache.root"])),
        ttl_s=int(raw["cache.ttl_s"]),
        temp_directory=temp_dir,
    )


def flatten_settings(
    resolved: Mapping[str, object], specs: Mapping[str, SettingSpec] | None = None
) -> dict[str, object]:
    """Return resolved values stripped of secret parameters for logs/manifests."""
    all_specs = specs if specs is not None else collect_specs()
    return {
        path: value
        for path, value in resolved.items()
        if path in all_specs and not all_specs[path].secret
    }


def render_dotenv(
    specs: Mapping[str, SettingSpec] | None = None,
    resolved: Mapping[str, object] | None = None,
) -> str:
    """Render a documented dotenv template with machine-derived defaults commented."""
    all_specs = specs if specs is not None else collect_specs()
    all_resolved = resolved if resolved is not None else resolve_settings()
    lines = [
        "# Generated dotenv template for EDGAR-SEC.",
        "# Secrets are omitted or masked; machine-derived defaults are commented out.",
        "",
    ]
    groups: dict[str, list[tuple[str, SettingSpec]]] = {}
    for path, spec in all_specs.items():
        groups.setdefault(path.split(".", 1)[0], []).append((path, spec))
    for group in sorted(groups):
        lines.append(f"# [{group}]")
        for path, spec in groups[group]:
            env_name = environment_name(path)
            if spec.description:
                lines.append(f"# {spec.description}")
            if spec.secret:
                lines.append(f"# {env_name}=<secret-value>")
                continue
            val = all_resolved.get(path, "")
            if callable(spec.default):
                lines.append(f"# {env_name}={val}")
            else:
                lines.append(f"{env_name}={val}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "MISSING",
    "RuntimeSettings",
    "SettingSpec",
    "collect_specs",
    "environment_name",
    "flatten_settings",
    "render_dotenv",
    "resolve_runtime_settings",
    "resolve_settings",
]
