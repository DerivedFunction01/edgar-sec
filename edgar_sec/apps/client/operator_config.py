"""Config-file host for the client operator: versioned JSON declarations.

One file declares session defaults, named sets, and an operation sequence.
Validation completes before anything executes, so a malformed file never
builds a partial session.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.render import ProseRow, render_output

__all__ = [
    "ACCEPTED_FORMAT_VERSION",
    "GATHERERS",
    "SPECS",
    "ConfigRun",
    "LoadConfigOptions",
    "ParsedConfig",
    "build_specs",
    "execute_config",
    "load_config_file",
    "parse_config",
    "register",
    "run_config_argv",
    "run_config_path",
    "settings_workers",
]

ACCEPTED_FORMAT_VERSION = "1.0"
_MODES = ("fast", "pipeline", "snapshot")
_SESSION_KEYS = frozenset({"mode", "snapshot", "workers"})
_SEED_KINDS = {
    "seed": "seed_query",
    "seed_query": "seed_query",
    "snapshot": "seed_snapshot",
    "seed_snapshot": "seed_snapshot",
    "company": "seed_company",
    "seed_company": "seed_company",
    "dataset": "seed_dataset",
    "seed_dataset": "seed_dataset",
}
_COMBINATORS = frozenset({"union", "intersect", "difference"})
_TOP_KEYS = frozenset({"format_version", "session", "sets", "operations"})


def _f(default: Any, help_text: str):
    return field(default=default, metadata={"help": help_text})


@dataclass(frozen=True, slots=True)
class LoadConfigOptions:
    """Options for loading a config file into the live session."""

    path: Path = _f(
        Path(""),
        "Config file to load. Its session defaults and declared sets are "
        "applied to the live session; its operation sequence is declared "
        "but not run. An empty path is refused.",
    )


class _Refusal(Exception):
    """A config refusal carrying a closed-vocabulary code and a message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.operations_declared = 0


@dataclass(frozen=True, slots=True)
class SetPlan:
    """One validated set declaration: its row id and decoded options."""

    name: str
    spec_id: str
    options: Any


@dataclass(frozen=True, slots=True)
class OpPlan:
    """One validated operation entry: its row and decoded options."""

    spec_id: str
    options: Any


@dataclass(frozen=True, slots=True)
class ParsedConfig:
    """A validated config file, ready to execute against a session."""

    session_decl: dict[str, Any]
    sets: tuple[SetPlan, ...]
    operations: tuple[OpPlan, ...]
    source: str = ""


@dataclass(frozen=True, slots=True)
class ConfigRun:
    """The outcome of one config execution, refusal included."""

    source: str = ""
    session_values: dict[str, Any] = field(default_factory=dict)
    session_sources: dict[str, str] = field(default_factory=dict)
    set_results: tuple = ()
    operation_results: tuple = ()
    operations_declared: int = 0
    error_code: str | None = None
    error_message: str = ""

    @property
    def ok(self) -> bool:
        """Whether the whole declared sequence executed without a refusal."""
        return self.error_code is None

    def to_payload(self) -> dict[str, Any]:
        """The one JSON document the argv host renders for a config run."""
        return {
            "path": self.source,
            "session": self.session_values,
            "session_sources": self.session_sources,
            "sets": [result.to_payload() for result in self.set_results],
            "operations": [result.to_payload() for result in self.operation_results],
            "operations_declared": self.operations_declared,
            "error_code": self.error_code,
            "message": self.error_message,
        }


def _invalid(message: str) -> _Refusal:
    return _Refusal("invalid_options", message)


def _registry(registry: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if registry is not None:
        return registry
    from edgar_sec.apps.client.operator import REGISTRY

    return REGISTRY


def _parse_session(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _invalid("session must be a JSON object")
    unknown = sorted(set(raw) - _SESSION_KEYS)
    if unknown:
        raise _invalid(f"unknown session field(s): {', '.join(unknown)}")
    decl: dict[str, Any] = {}
    mode = raw.get("mode")
    if mode is not None:
        if mode not in _MODES:
            raise _invalid(f"unknown session mode: {mode!r}")
        decl["mode"] = mode
    snapshot = raw.get("snapshot")
    if snapshot is not None:
        if not isinstance(snapshot, str):
            raise _invalid("session snapshot must be a string or null")
        if snapshot:
            decl["snapshot"] = snapshot
    workers = raw.get("workers")
    if workers is not None:
        if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
            raise _invalid("session workers must be a positive integer or null")
        decl["workers"] = workers
    return decl


def _decode(registry: Mapping[str, Any], spec_id: str, raw: Mapping[str, Any]):
    from edgar_sec.apps.client.operator import decode_options

    return decode_options(registry[spec_id], dict(raw))


def _parse_seed(
    registry: Mapping[str, Any], name: str, kind: str, value: Any, spec_id: str
) -> SetPlan:
    if not isinstance(value, dict):
        raise _invalid(f"set {name}: a {kind} declaration must be a JSON object")
    into = value.get("into")
    if into is not None and into != name:
        raise _invalid(f"set {name}: its into names a different set ({into})")
    try:
        options = _decode(registry, spec_id, {**value, "into": name})
    except ValueError as exc:
        raise _invalid(f"set {name}: {exc}") from exc
    return SetPlan(name=name, spec_id=spec_id, options=options)


def _parse_combinator(name: str, kind: str, value: Any, declared: set[str]) -> SetPlan:
    if isinstance(value, list):
        if len(value) != 2 or not all(isinstance(item, str) for item in value):
            raise _invalid(f"set {name}: {kind} names exactly two sets")
        left, right = value
    elif isinstance(value, dict):
        unknown = sorted(set(value) - {"left", "right", "into"})
        if unknown:
            raise _invalid(f"set {name}: unknown field(s): {', '.join(unknown)}")
        into = value.get("into")
        if into is not None and into != name:
            raise _invalid(f"set {name}: its into names a different set ({into})")
        left, right = value.get("left"), value.get("right")
        if not isinstance(left, str) or not isinstance(right, str):
            raise _invalid(f"set {name}: {kind} needs left and right set names")
    else:
        raise _invalid(f"set {name}: a {kind} declaration names two sets")
    for ref in (left, right):
        if ref not in declared:
            raise _invalid(f"set {name}: {kind} references undeclared set {ref}")
    from edgar_sec.apps.client.operator_selection import CombineOptions

    options = CombineOptions(left=left, right=right, into=name)
    return SetPlan(name=name, spec_id=kind, options=options)


def _parse_sets(registry: Mapping[str, Any], raw: Any) -> tuple[SetPlan, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise _invalid("sets must be a JSON object of named declarations")
    plans: list[SetPlan] = []
    declared: set[str] = set()
    for name, decl in raw.items():
        if not isinstance(name, str) or not name:
            raise _invalid("set names must be non-empty strings")
        if not isinstance(decl, dict) or len(decl) != 1:
            raise _invalid(f"set {name}: a declaration carries exactly one kind")
        kind, value = next(iter(decl.items()))
        if kind in _SEED_KINDS:
            plan = _parse_seed(registry, name, kind, value, _SEED_KINDS[kind])
        elif kind in _COMBINATORS:
            plan = _parse_combinator(name, kind, value, declared)
        else:
            raise _invalid(
                f"set {name}: unknown set declaration kind {kind!r} (a seed "
                "kind or a combinator: union, intersect, difference)"
            )
        plans.append(plan)
        declared.add(name)
    return tuple(plans)


def _parse_operations(registry: Mapping[str, Any], raw: Any) -> tuple[OpPlan, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _invalid("operations must be a JSON array")
    plans: list[OpPlan] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise _invalid("each operation entry must be a JSON object")
        op_id = entry.get("op")
        if not isinstance(op_id, str) or not op_id:
            raise _invalid("each operation entry names its operation id as op")
        if op_id not in registry:
            raise _invalid(f"unknown operation id: {op_id}")
        raw_options: dict[str, Any] = {
            key: value for key, value in entry.items() if key not in ("op", "options")
        }
        nested = entry.get("options")
        if nested is not None:
            if not isinstance(nested, dict):
                raise _invalid(f"operation {op_id}: options must be a JSON object")
            raw_options.update(nested)
        try:
            options = _decode(registry, op_id, raw_options)
        except ValueError as exc:
            raise _invalid(f"operation {op_id}: {exc}") from exc
        plans.append(OpPlan(spec_id=op_id, options=options))
    return tuple(plans)


def parse_config(
    payload: Any,
    *,
    source: str = "",
    registry: Mapping[str, Any] | None = None,
) -> ParsedConfig:
    """Validate one config document whole, before anything executes."""
    specs = _registry(registry)
    if not isinstance(payload, dict):
        raise _invalid("a config file must be a JSON object")
    unknown = sorted(set(payload) - _TOP_KEYS)
    if unknown:
        raise _invalid(f"unknown config field(s): {', '.join(unknown)}")
    if "format_version" not in payload:
        raise _invalid("format_version is required")
    version = payload["format_version"]
    if version != ACCEPTED_FORMAT_VERSION:
        raise _Refusal(
            "unsupported_version",
            f"unsupported format_version {version!r}: "
            f"this operator accepts {ACCEPTED_FORMAT_VERSION!r}",
        )
    return ParsedConfig(
        session_decl=_parse_session(payload.get("session")),
        sets=_parse_sets(specs, payload.get("sets")),
        operations=_parse_operations(specs, payload.get("operations")),
        source=source,
    )


def load_config_file(
    path: Path, *, registry: Mapping[str, Any] | None = None
) -> ParsedConfig:
    """Read and validate one config file; refusals precede any execution."""
    target = Path(path)
    if not target.is_file():
        raise _Refusal("not_found", f"no config file: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _invalid(f"config file is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise _Refusal("not_found", f"config file cannot be read: {exc}") from exc
    declared = 0
    if isinstance(payload, dict) and isinstance(payload.get("operations"), list):
        declared = len(payload["operations"])
    try:
        return parse_config(payload, source=str(target), registry=registry)
    except _Refusal as refusal:
        refusal.operations_declared = declared
        raise


def settings_workers() -> int | None:
    """The settings-provider worker default, resolved as the facade resolves it."""
    try:
        from edgar_sec.foundation.runtime.settings import resolve_settings

        return int(resolve_settings(include=["runtime"])["runtime.workers"])
    except Exception:  # noqa: BLE001 - no settings value means no default level
        return None


def _resolve_session(
    session: Any,
    parsed: ParsedConfig,
    host_overrides: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Resolve each session field: host, then config, then session, then settings."""
    host = dict(host_overrides or {})
    for key in host:
        if key not in _SESSION_KEYS:
            raise _invalid(f"unknown host override: {key}")
    if "mode" in host and host["mode"] not in _MODES:
        raise _invalid(f"unknown mode: {host['mode']!r}")
    if "workers" in host and (
        isinstance(host["workers"], bool)
        or not isinstance(host["workers"], int)
        or host["workers"] < 1
    ):
        raise _invalid("workers must be a positive integer")
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    context = session.read_context
    for key, fallback in (("mode", context.mode), ("snapshot", context.snapshot)):
        if host.get(key):
            values[key], sources[key] = host[key], "host"
        elif key in parsed.session_decl:
            values[key], sources[key] = parsed.session_decl[key], "config"
        else:
            values[key], sources[key] = fallback, "session"
    session_workers = getattr(session, "workers", None)
    if host.get("workers") is not None:
        values["workers"], sources["workers"] = host["workers"], "host"
    elif "workers" in parsed.session_decl:
        values["workers"], sources["workers"] = parsed.session_decl["workers"], "config"
    elif session_workers is not None:
        values["workers"], sources["workers"] = session_workers, "session"
    else:
        values["workers"], sources["workers"] = settings_workers(), "settings"
    return values, sources


def _apply_session(session: Any, values: Mapping[str, Any]) -> None:
    session.read_context.mode = values["mode"]
    session.read_context.snapshot = values["snapshot"]
    session.workers = values["workers"]


def _with_workers(options: Any, workers: int | None) -> Any:
    names = {item.name for item in fields(options)}
    if "workers" in names and workers is not None:
        if getattr(options, "workers") is None:
            return replace(options, workers=workers)
    return options


def execute_config(
    session: Any,
    parsed: ParsedConfig,
    host_overrides: Mapping[str, Any] | None = None,
    *,
    run_operations: bool = True,
    registry: Mapping[str, Any] | None = None,
) -> ConfigRun:
    """Apply one validated config to ``session`` and run its sequence in order.

    The first refusal or failure stops the run; later declarations and
    operations do not execute and no partial success is claimed.
    """
    specs = _registry(registry)
    base = {"source": parsed.source, "operations_declared": len(parsed.operations)}
    try:
        values, sources = _resolve_session(session, parsed, host_overrides)
    except _Refusal as refusal:
        return ConfigRun(error_code=refusal.code, error_message=refusal.message, **base)
    _apply_session(session, values)
    base.update(session_values=values, session_sources=sources)
    from edgar_sec.apps.client.operator import execute_operation

    set_results: list = []
    for plan in parsed.sets:
        result = execute_operation(specs[plan.spec_id], session, plan.options)
        set_results.append(result)
        if result.error_code:
            return ConfigRun(
                set_results=tuple(set_results),
                error_code=result.error_code,
                error_message=str(result.to_payload()["message"] or ""),
                **base,
            )
    operation_results: list = []
    if run_operations:
        for plan in parsed.operations:
            options = _with_workers(plan.options, values["workers"])
            result = execute_operation(specs[plan.spec_id], session, options)
            operation_results.append(result)
            if result.error_code:
                return ConfigRun(
                    set_results=tuple(set_results),
                    operation_results=tuple(operation_results),
                    error_code=result.error_code,
                    error_message=str(result.to_payload()["message"] or ""),
                    **base,
                )
    return ConfigRun(
        set_results=tuple(set_results),
        operation_results=tuple(operation_results),
        **base,
    )


def run_config_path(
    session: Any,
    path: Path,
    host_overrides: Mapping[str, Any] | None = None,
    *,
    run_operations: bool = True,
    registry: Mapping[str, Any] | None = None,
) -> ConfigRun:
    """Load one config file and execute it against ``session``."""
    try:
        parsed = load_config_file(Path(path), registry=registry)
    except _Refusal as refusal:
        return ConfigRun(
            source=str(path),
            operations_declared=refusal.operations_declared,
            error_code=refusal.code,
            error_message=refusal.message,
        )
    return execute_config(
        session,
        parsed,
        host_overrides,
        run_operations=run_operations,
        registry=registry,
    )


def _error_result(code: str, title: str, message: str, data: dict | None = None):
    from edgar_sec.apps.client.operator import OpResult

    return OpResult(
        kind="key_value",
        title=title,
        components=(ProseRow(message),) if message else (),
        data={**(data or {}), "message": message},
        error_code=code,
    )


def _execute_load_config(options: LoadConfigOptions, session: Any):
    from edgar_sec.apps.client.operator import OpResult
    from edgar_sec.foundation.runtime.render import KeyValueRow

    title = "Load config"
    if str(options.path) in ("", "."):
        return _error_result("invalid_options", title, "a config path is required")
    run = run_config_path(session, options.path, run_operations=False)
    if not run.ok:
        return _error_result(
            str(run.error_code), title, run.error_message, {"path": run.source}
        )
    sets = {name: len(working) for name, working in session.sets.items()}
    values = run.session_values
    data = {
        "path": run.source,
        "format_version": ACCEPTED_FORMAT_VERSION,
        "session": values,
        "session_sources": run.session_sources,
        "sets": sets,
        "operations_declared": run.operations_declared,
        "operations_run": 0,
    }
    rows = (
        ("path", run.source),
        ("mode", str(values["mode"])),
        ("snapshot", str(values["snapshot"] or "none")),
        ("workers", str(values["workers"])),
        ("sets built", str(len(run.set_results))),
        ("operations declared (not run)", str(run.operations_declared)),
    )
    components = tuple(KeyValueRow(key, value) for key, value in rows)
    return OpResult(
        kind="key_value",
        title=title,
        components=components,
        data=data,
        total=len(components),
        shown=len(components),
        hints=("vars", "fetch"),
    )


def build_specs() -> tuple:
    """Build this module's registry rows; operator imports resolve at call time."""
    from edgar_sec.apps.client.operator import OperationSpec

    return (
        OperationSpec(
            id="load_config",
            label="Load config file",
            options_type=LoadConfigOptions,
            effect="reads_state",
            requires="none",
            result_kind="key_value",
            hints=("vars", "session_summary"),
            executor=_execute_load_config,
        ),
    )


def register(registry: dict) -> dict:
    """Add this module's rows to ``registry``, refusing duplicate ids."""
    from edgar_sec.apps.client.operator import assemble_registry

    specs = build_specs()
    assemble_registry(registry.values(), specs)
    for spec in specs:
        registry[spec.id] = spec
    return registry


def __getattr__(name: str):
    if name == "SPECS":
        return build_specs()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _gather_load_config(session: Any) -> LoadConfigOptions:
    from edgar_sec.apps.client.operator_selection import _gather_options

    return _gather_options(session, LoadConfigOptions)


GATHERERS: dict[str, Callable[[Any], Any]] = {"load_config": _gather_load_config}


def _argv_error(code: str, message: str, json_output: bool) -> int:
    from edgar_sec.apps.client.operator import OpResult

    result = OpResult(
        kind="object",
        title="Run config",
        components=(ProseRow(message),),
        data={"message": message},
        error_code=code,
    )
    if json_output:
        print(json.dumps(result.to_payload(), indent=2))
    else:
        render_output(result.components, title=result.title)
        print(f"error_code: {code}")
    return 1


def run_config_argv(rest: list[str], session: Any) -> int:
    """The argv config host: ``--config <file>`` plus host-explicit overrides."""
    json_output = "--json" in rest
    if not rest or rest[0] in ("--json", "--mode", "--snapshot", "--workers"):
        return _argv_error(
            "invalid_options", "a config file path is required", json_output
        )
    path, tokens = rest[0], rest[1:]
    overrides: dict[str, Any] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--json":
            index += 1
        elif token in ("--mode", "--snapshot", "--workers"):
            if index + 1 >= len(tokens):
                return _argv_error(
                    "invalid_options", f"{token} needs a value", json_output
                )
            value: Any = tokens[index + 1]
            if token == "--workers":
                try:
                    value = int(value)
                except ValueError:
                    return _argv_error(
                        "invalid_options", "--workers needs an integer", json_output
                    )
            overrides[token[2:]] = value
            index += 2
        else:
            return _argv_error(
                "invalid_options", f"unknown argument: {token}", json_output
            )
    run = run_config_path(session, Path(path), overrides)
    if json_output:
        print(json.dumps(run.to_payload(), indent=2))
        return 0 if run.ok else 1
    results = (*run.set_results, *run.operation_results)
    for result in results:
        if result.components:
            render_output(result.components, title=result.title)
        if result.error_code:
            print(f"error_code: {result.error_code}")
    if not results and run.error_code:
        render_output((ProseRow(run.error_message),), title="Run config")
        print(f"error_code: {run.error_code}")
    return 0 if run.ok else 1
