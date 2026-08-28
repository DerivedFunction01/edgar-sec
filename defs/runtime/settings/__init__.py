"""Typed settings registry: spec model, collection, resolution, rendering.

Setting identity is a logical dotted path (``duckdb.threads``); environment
names are derived from the path, never hand-written. Spec modules export one
``SETTING_SPECS`` dictionary of nested dictionaries of :class:`SettingSpec`
and must not export individual environment names. Resolution always flows
through :mod:`defs.runtime.env` (direct process environment, then the single
canonical dotenv file) so no module invents its own environment contract.
"""

from __future__ import annotations

import importlib
import inspect
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ..env import get_env

#: Sentinel distinguishing "no value" from explicit ``None``/``False``/``0``.
MISSING = object()

_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Shared spec modules in deterministic resolution order. Dependent defaults
# (factories taking the resolved-so-far mapping) rely on this ordering.
SHARED_SPEC_MODULES = (
    "defs.runtime.settings.runtime",
    "defs.runtime.settings.paths",
    "defs.runtime.settings.sec",
)


@dataclass(frozen=True)
class SettingSpec:
    """One logical setting and how it may be supplied.

    ``default`` is a static value, a zero-argument factory (machine-derived),
    a one-argument factory receiving the resolved-so-far mapping (dependent),
    or :data:`MISSING` when the caller must supply a fallback.
    """

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

    ``duckdb.threads`` becomes ``DUCKDB_THREADS``; hyphens map to
    underscores. Names are always generated, never declared per module.
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
            raise ValueError(
                f"malformed setting spec at {path!r}: expected SettingSpec or mapping"
            )


def collect_specs(phase: str | None = None) -> dict[str, SettingSpec]:
    """Collect shared specs, plus one phase's specs when requested.

    Duplicate logical paths or malformed spec trees raise ``ValueError``
    before any command runs.
    """
    specs: dict[str, SettingSpec] = {}
    for module_name in SHARED_SPEC_MODULES:
        module = importlib.import_module(module_name)
        group = getattr(module, "SETTING_SPECS", None)
        if not isinstance(group, Mapping):
            raise ValueError(f"{module_name} must export a SETTING_SPECS mapping")
        _flatten_group(group, "", specs)
    if phase is not None:
        barrel = importlib.import_module("phases.settings")
        module_name = barrel.phase_settings_module(phase)
        module = importlib.import_module(module_name)
        group = getattr(module, "SETTING_SPECS", None)
        if not isinstance(group, Mapping):
            raise ValueError(f"{module_name} must export a SETTING_SPECS mapping")
        _flatten_group(group, "", specs)
    return specs


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


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


def _env_raw_value(path: str, env: Mapping[str, str] | None) -> object:
    """Resolve one raw environment value through the shared env layer.

    An explicit ``env`` mapping replaces process/dotenv resolution entirely
    (deterministic tests and path resolution). ``MISSING`` means unset; an
    empty string also means unset, matching :func:`defs.runtime.env.get_env`.
    """
    if env is not None:
        name = environment_name(path)
        return env.get(name, MISSING)
    return get_env(environment_name(path), default=MISSING)


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
    phase: str | None = None,
    config: Mapping[str, object] | None = None,
    cli_overrides: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    include: Iterable[str] | None = None,
    fallbacks: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Resolve settings to typed values.

    Precedence for each spec: explicit CLI override, then direct
    environment/dotenv when ``env=True``, then persisted config when
    ``config=True``, then the default/factory. An explicit ``env`` mapping
    bypasses the process environment and dotenv file entirely. Empty
    environment values count as unset so false/zero defaults survive, while
    explicit ``"0"``/``"false"`` values parse normally.
    """
    specs = collect_specs(phase)
    if include is not None:
        include = tuple(include)
        specs = {p: s for p, s in specs.items() if _included(p, include)}
    resolved: dict[str, object] = {}
    for path, spec in specs.items():
        value: object = MISSING
        if cli_overrides is not None and cli_overrides.get(path) is not None:
            value = _check_typed_value(spec, path, cli_overrides[path])
        elif spec.env:
            raw = _env_raw_value(path, env)
            if raw is not MISSING and raw != "":
                value = _parse_value(spec, path, raw)
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
            raise ValueError(
                f"setting {path!r} has no value; supply it via environment, "
                "config, CLI, or a fallback"
            )
        if spec.validate is not None:
            try:
                spec.validate(value)
            except ValueError as exc:
                raise ValueError(f"invalid value for setting {path!r}: {exc}") from exc
        resolved[path] = value
    return resolved


def resolve_runtime_settings(
    config: Mapping[str, object] | None = None,
    cli_overrides: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    include: Iterable[str] | None = None,
) -> dict[str, object]:
    """Resolve shared runtime settings."""
    return resolve_settings(
        phase=None,
        config=config,
        cli_overrides=cli_overrides,
        env=env,
        include=include or ("runtime", "artifacts", "cache", "sec"),
    )


def resolve_phase_settings(
    phase: str,
    phase_config: Mapping[str, object] | None = None,
    runtime_settings: Mapping[str, object] | None = None,
    cli_overrides: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Resolve phase settings combined with runtime settings."""
    merged_config = dict(runtime_settings or {})
    if phase_config:
        merged_config.update(phase_config)
    return resolve_settings(
        phase=phase,
        config=merged_config,
        cli_overrides=cli_overrides,
        env=env,
    )


def get_setting(
    path: str,
    *,
    phase: str | None = None,
    config: Mapping[str, object] | None = None,
    cli_overrides: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    fallbacks: Mapping[str, object] | None = None,
) -> object:
    """Resolve one setting, expanding to its whole top-level group so
    dependent defaults see the values they rely on."""
    resolved = resolve_settings(
        phase=phase,
        config=config,
        cli_overrides=cli_overrides,
        env=env,
        include=[path.split(".", 1)[0]],
        fallbacks=fallbacks,
    )
    try:
        return resolved[path]
    except KeyError:
        raise ValueError(f"unknown setting {path!r}") from None


def flatten_settings(
    resolved: Mapping[str, object], specs: Mapping[str, SettingSpec] | None = None
) -> dict[str, object]:
    """Resolved values without secrets, for reports and manifests."""
    specs = specs if specs is not None else collect_specs()
    return {path: value for path, value in resolved.items() if not specs[path].secret}


def _render_value(value: object) -> str:
    if isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    return text.encode("ascii", "backslashreplace").decode("ascii")


def render_dotenv(
    specs: Mapping[str, SettingSpec], resolved: Mapping[str, object]
) -> str:
    """Render a documented dotenv template from collected specs.

    Static defaults render as real assignments; machine-derived defaults
    (callable factories) and caller-fallback settings render as commented
    suggestions so a workspace does not freeze one machine's resources.
    Secret settings are omitted entirely with a safe explanatory comment.
    """
    lines = [
        "# Generated by `python run.py settings generate-dotenv`.",
        "# Values below are defaults; machine-derived suggestions are",
        "# commented out so this file never freezes one machine's resources.",
        "",
    ]
    groups: dict[str, list[tuple[str, SettingSpec]]] = {}
    for path, spec in specs.items():
        groups.setdefault(path.split(".", 1)[0], []).append((path, spec))
    for group_index, group in enumerate(sorted(groups)):
        if group_index:
            lines.append("")
        lines.append(f"# {group}")
        for path, spec in groups[group]:
            name = environment_name(path)
            if spec.description:
                lines.append(f"# {path}: {spec.description}")
            if spec.secret:
                lines.append(
                    f"# {name} is omitted on purpose: {path} is a secret and"
                    " must be set directly in this file when needed"
                )
                continue
            value = resolved.get(path, MISSING)
            if value is not MISSING and value != "" and not callable(spec.default):
                lines.append(f"{name}={_render_value(value)}")
            elif value is not MISSING and value != "":
                lines.append(f"# {name}={_render_value(value)}")
            else:
                lines.append(f"# {name}=")
    return "\n".join(lines) + "\n"


__all__ = [
    "MISSING",
    "SHARED_SPEC_MODULES",
    "SettingSpec",
    "collect_specs",
    "environment_name",
    "flatten_settings",
    "get_setting",
    "render_dotenv",
    "resolve_phase_settings",
    "resolve_runtime_settings",
    "resolve_settings",
]
