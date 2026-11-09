"""Client operator: a held session, one operation registry, and its hosts.

Rows execute against ``ClientSession``; the menu host holds one session and
the argv host builds an ephemeral one, falling back to the fetch CLI branch.
"""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

from edgar_sec.apps.client import cli
from edgar_sec.apps.client.operator_discovery import (
    help_components,
    listing_components,
    operation_help,
    operation_listing,
)
from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    MenuSeparator,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_text,
)
from edgar_sec.foundation.runtime.render import (
    KeyValueRow,
    ProseRow,
    RenderComponent,
    render_output,
)

__all__ = [
    "EFFECTS",
    "ERROR_CODES",
    "GATHERERS",
    "REGISTRY",
    "REQUIREMENTS",
    "RESULT_KINDS",
    "ClientSession",
    "CurrentFiling",
    "OpResult",
    "OperationSpec",
    "ReadContext",
    "SessionSummaryOptions",
    "WorkingSet",
    "assemble_registry",
    "build_operator_menu",
    "decode_options",
    "execute_by_id",
    "execute_operation",
    "main",
    "render_session_header",
]

MENU_TITLE = "Filing Runner & Fetch"
INTERRUPTED_MESSAGE = "Action cancelled by user."

EFFECTS = frozenset(
    {"reads_state", "mutates_selection", "moves_position", "external", "destructive"}
)
REQUIREMENTS = frozenset({"none", "selection", "current_filing", "snapshot_context"})
RESULT_KINDS = frozenset({"grid", "key_value", "prose", "object"})
ERROR_CODES = frozenset(
    {
        "invalid_options",
        "missing_context",
        "unknown_operation",
        "refused",
        "not_found",
        "absent",
        "external_failure",
        "unsupported_version",
    }
)


@dataclass(frozen=True, slots=True)
class WorkingSet:
    """A named selection: its accession set plus the retained result object."""

    accessions: frozenset[str]
    result: Any = None

    def __len__(self) -> int:
        return len(self.accessions)


@dataclass(slots=True)
class ReadContext:
    """Where reads resolve: the engine mode and the snapshot selector."""

    mode: str = "fast"
    snapshot: str = "main"


@dataclass(frozen=True, slots=True)
class CurrentFiling:
    """The drill-down position: an accession and its retained aggregate."""

    accession: str
    aggregate: Any = None


class ClientSession:
    """Held operator state; the facade is built lazily on first access."""

    def __init__(
        self,
        facade: Any = None,
        *,
        read_context: ReadContext | None = None,
        workers: int | None = None,
    ) -> None:
        self._facade = facade
        self.workers = workers
        self.sets: dict[str, WorkingSet] = {}
        self.current_set_name: str = ""
        self.read_context = read_context or ReadContext()
        self.current_filing: CurrentFiling | None = None
        self.last_run_record: str = ""

    @property
    def facade(self) -> Any:
        """The held facade, constructing the real client only when asked."""
        if self._facade is None:
            from edgar_sec.apps.client.facade import Edgar

            self._facade = Edgar()
        return self._facade

    @property
    def current_set(self) -> WorkingSet | None:
        """The working set the current set name denotes, if any."""
        return self.sets.get(self.current_set_name)

    def add_set(
        self, name: str, accessions: Iterable[str], result: Any = None
    ) -> WorkingSet:
        """Store a named set and make it the current set."""
        working = WorkingSet(accessions=frozenset(accessions), result=result)
        self.sets[name] = working
        self.current_set_name = name
        return working

    def select_filing(self, accession: str, aggregate: Any = None) -> CurrentFiling:
        """Move the drill-down position to one filing."""
        self.current_filing = CurrentFiling(accession=accession, aggregate=aggregate)
        return self.current_filing

    def clear_filing(self) -> None:
        """Clear the drill-down position."""
        self.current_filing = None

    def satisfies(self, requires: str) -> bool:
        """Whether this session currently meets one context requirement."""
        if requires == "none":
            return True
        if requires == "selection":
            return self.current_set is not None
        if requires == "current_filing":
            return self.current_filing is not None and bool(
                self.current_filing.accession
            )
        if requires == "snapshot_context":
            return bool(self.read_context.snapshot)
        return False


@dataclass(frozen=True, slots=True)
class OpResult:
    """One operation outcome; ``total``/``shown`` declare the clamp, if any."""

    kind: str
    title: str = ""
    components: tuple[RenderComponent, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)
    total: int = 0
    shown: int = 0
    error_code: str | None = None
    hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in RESULT_KINDS:
            raise ValueError(f"unknown result kind: {self.kind!r}")
        if self.error_code is not None and self.error_code not in ERROR_CODES:
            raise ValueError(f"unknown error code: {self.error_code!r}")
        if self.total < 0 or self.shown < 0 or self.shown > self.total:
            raise ValueError("shown must lie between 0 and total")

    def to_payload(self) -> dict[str, Any]:
        """The JSON-native rendering every operation offers."""
        message: str | None = None
        if self.error_code is not None:
            prose = next(
                (row.text for row in self.components if isinstance(row, ProseRow)),
                None,
            )
            carried = self.data.get("message")
            message = (
                prose if prose is not None else (str(carried) if carried else None)
            )
        return {
            "kind": self.kind,
            "title": self.title,
            "data": self.data,
            "total": self.total,
            "shown": self.shown,
            "error_code": self.error_code,
            "message": message,
            "hints": list(self.hints),
        }


Executor = Callable[[Any, ClientSession], OpResult]


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """One registry row: typed options, closed vocabularies, one executor."""

    id: str
    label: str
    options_type: type
    effect: str
    requires: str
    result_kind: str
    hints: tuple[str, ...] = ()
    executor: Executor | None = None
    available: Callable[[ClientSession], bool] | None = None

    def __post_init__(self) -> None:
        if self.effect not in EFFECTS:
            raise ValueError(f"unknown effect: {self.effect!r}")
        if self.requires not in REQUIREMENTS:
            raise ValueError(f"unknown requirement: {self.requires!r}")
        if self.result_kind not in RESULT_KINDS:
            raise ValueError(f"unknown result kind: {self.result_kind!r}")
        if not is_dataclass(self.options_type):
            raise ValueError(f"options_type is not a dataclass: {self.options_type!r}")
        if not callable(self.executor):
            raise ValueError(f"executor is not callable for operation {self.id!r}")


def _error_result(
    kind: str, code: str, title: str, message: str, data: dict[str, Any] | None = None
) -> OpResult:
    return OpResult(
        kind=kind,
        title=title,
        components=(ProseRow(message),) if message else (),
        data=data or {},
        error_code=code,
    )


def _coerce(value: Any, annotation: Any) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is Any or annotation is None:
        return value
    if origin is Union or isinstance(annotation, types.UnionType):
        if value is None and type(None) in args:
            return None
        for candidate in args:
            if candidate is type(None):
                continue
            try:
                return _coerce(value, candidate)
            except (TypeError, ValueError):
                continue
        raise ValueError(f"cannot coerce {value!r} to {annotation}")
    if annotation is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "yes", "1"}:
            return True
        if isinstance(value, str) and value.lower() in {"false", "no", "0"}:
            return False
        raise ValueError(f"cannot coerce {value!r} to bool")
    if annotation is int:
        if isinstance(value, bool):
            raise ValueError(f"cannot coerce {value!r} to int")
        return int(value)
    if annotation is float:
        if isinstance(value, bool):
            raise ValueError(f"cannot coerce {value!r} to float")
        return float(value)
    if annotation is str:
        if not isinstance(value, str):
            raise ValueError(f"cannot coerce {value!r} to str")
        return value
    if annotation is Path:
        return Path(str(value))
    if origin in (tuple, list, frozenset, set) or annotation in (
        tuple,
        list,
        frozenset,
        set,
    ):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"cannot coerce {value!r} to a sequence")
        element = args[0] if args and args[0] is not Ellipsis else Any
        items = [_coerce(item, element) for item in value]
        container = origin or annotation
        return container(items)
    if isinstance(annotation, type) and isinstance(value, annotation):
        return value
    if isinstance(annotation, type):
        return annotation(value)
    return value


def decode_options(spec: OperationSpec, raw: Mapping[str, Any] | None) -> Any:
    """Decode a JSON-native mapping into the row's options dataclass."""
    values = dict(raw or {})
    hints = get_type_hints(spec.options_type)
    known = {item.name for item in fields(spec.options_type)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(f"unknown option field(s): {', '.join(unknown)}")
    kwargs: dict[str, Any] = {}
    for item in fields(spec.options_type):
        if item.name in values:
            kwargs[item.name] = _coerce(
                values[item.name], hints.get(item.name, item.type)
            )
    try:
        return spec.options_type(**kwargs)
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc


def execute_operation(
    spec: OperationSpec, session: ClientSession, options: Any = None
) -> OpResult:
    """Execute one row, mapping every failure onto the closed error vocabulary."""
    if options is None:
        try:
            options = spec.options_type()
        except (TypeError, ValueError) as exc:
            return _error_result(
                spec.result_kind, "invalid_options", spec.label, str(exc)
            )
    if not isinstance(options, spec.options_type):
        return _error_result(
            spec.result_kind,
            "invalid_options",
            spec.label,
            f"options must be {spec.options_type.__name__}",
        )
    if not session.satisfies(spec.requires):
        return _error_result(
            spec.result_kind,
            "missing_context",
            spec.label,
            f"operation requires {spec.requires}",
            {"requires": spec.requires},
        )
    try:
        result = spec.executor(options, session)
    except Exception as exc:  # noqa: BLE001 - executor failures become coded results
        return _error_result(spec.result_kind, "external_failure", spec.label, str(exc))
    if not isinstance(result, OpResult) or result.kind != spec.result_kind:
        return _error_result(
            spec.result_kind,
            "external_failure",
            spec.label,
            "executor returned a result of the wrong kind",
        )
    return result


def execute_by_id(
    op_id: str,
    session: ClientSession,
    raw_options: Mapping[str, Any] | None = None,
    registry: Mapping[str, OperationSpec] | None = None,
) -> OpResult:
    """Resolve, decode, and execute one operation by registry id."""
    specs = REGISTRY if registry is None else registry
    spec = specs.get(op_id)
    if spec is None:
        return _error_result(
            "object",
            "unknown_operation",
            op_id,
            f"unknown operation: {op_id}",
            {"operation": op_id},
        )
    try:
        options = decode_options(spec, raw_options)
    except ValueError as exc:
        return _error_result(spec.result_kind, "invalid_options", spec.label, str(exc))
    return execute_operation(spec, session, options)


@dataclass(frozen=True, slots=True)
class SessionSummaryOptions:
    """Options for the session summary row."""

    include_sets: bool = field(
        default=True,
        metadata={
            "help": "Selects whether named working sets are listed with their "
            "counts. No refusal rules apply."
        },
    )


def _execute_session_summary(
    options: SessionSummaryOptions, session: ClientSession
) -> OpResult:
    current = session.current_set
    filing = session.current_filing.accession if session.current_filing else ""
    data: dict[str, Any] = {
        "mode": session.read_context.mode,
        "snapshot": session.read_context.snapshot,
        "current_set": session.current_set_name,
        "current_set_count": len(current) if current is not None else 0,
        "current_filing": filing,
        "set_count": len(session.sets),
    }
    rows: list[RenderComponent] = [
        KeyValueRow("mode", data["mode"]),
        KeyValueRow("snapshot", data["snapshot"] or "none"),
        KeyValueRow(
            "current set",
            f"{data['current_set'] or 'none'} ({data['current_set_count']})",
        ),
        KeyValueRow("current filing", filing or "none"),
    ]
    if options.include_sets:
        data["sets"] = {name: len(item) for name, item in session.sets.items()}
        rows.extend(
            KeyValueRow(f"set {name}", str(len(item)))
            for name, item in session.sets.items()
        )
    return OpResult(
        kind="key_value",
        title="Session summary",
        components=tuple(rows),
        data=data,
        total=len(data),
        shown=len(data),
        hints=("list operations to discover the next operation",),
    )


_CORE_SPECS: tuple[OperationSpec, ...] = (
    OperationSpec(
        id="session_summary",
        label="Session summary",
        options_type=SessionSummaryOptions,
        effect="reads_state",
        requires="none",
        result_kind="key_value",
        hints=("list operations to discover the next operation",),
        executor=_execute_session_summary,
    ),
)


def assemble_registry(
    *groups: Iterable[OperationSpec],
) -> dict[str, OperationSpec]:
    """Assemble the ordered registry, refusing duplicate operation ids."""
    registry: dict[str, OperationSpec] = {}
    for group in groups:
        for spec in group:
            if spec.id in registry:
                raise ValueError(f"duplicate operation id: {spec.id}")
            registry[spec.id] = spec
    return registry


# Sibling row modules contribute through a register(registry) function and a
# GATHERERS dict of menu prompt producers, assembled explicitly here.
REGISTRY: dict[str, OperationSpec] = assemble_registry(_CORE_SPECS)
GATHERERS: dict[str, Callable[[ClientSession], Any]] = {}


def _register_sibling_rows() -> None:
    from edgar_sec.apps.client import (
        operator_company,
        operator_config,
        operator_drill,
        operator_drill_exhibits,
        operator_fetch,
        operator_run_records,
        operator_selection,
        operator_state,
        operator_tools,
    )

    operator_selection.register(REGISTRY)
    GATHERERS.update(operator_selection.GATHERERS)
    operator_fetch.register(REGISTRY)
    GATHERERS.update(operator_fetch.GATHERERS)
    operator_run_records.register(REGISTRY)
    GATHERERS.update(operator_run_records.GATHERERS)
    operator_drill.register(REGISTRY)
    GATHERERS.update(operator_drill.GATHERERS)
    operator_drill_exhibits.register(REGISTRY)
    GATHERERS.update(operator_drill_exhibits.GATHERERS)
    operator_tools.register(REGISTRY)
    GATHERERS.update(operator_tools.GATHERERS)
    operator_company.register(REGISTRY)
    GATHERERS.update(operator_company.GATHERERS)
    operator_state.register(REGISTRY)
    GATHERERS.update(operator_state.GATHERERS)
    operator_config.register(REGISTRY)
    GATHERERS.update(operator_config.GATHERERS)


_register_sibling_rows()


def render_session_header(session: ClientSession) -> str:
    """The per-loop header: mode, snapshot, current set and filing."""
    current = session.current_set
    count = len(current) if current is not None else 0
    filing = session.current_filing.accession if session.current_filing else "none"
    snapshot = session.read_context.snapshot or "none"
    name = session.current_set_name or "none"
    return (
        f"mode: {session.read_context.mode} · snapshot: {snapshot} · "
        f"current set: {name} ({count}) · current filing: {filing}"
    )


def _run_and_render(spec: OperationSpec, session: ClientSession) -> None:
    gatherer = GATHERERS.get(spec.id)
    if gatherer is not None and session.satisfies(spec.requires):
        try:
            options = gatherer(session)
        except ValueError as exc:
            result = _error_result(
                spec.result_kind, "invalid_options", spec.label, str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - a gather failure is a coded result
            result = _error_result(
                spec.result_kind, "external_failure", spec.label, str(exc)
            )
        else:
            result = execute_operation(spec, session, options)
    else:
        result = execute_operation(spec, session)
    if result.components:
        render_output(result.components, title=result.title)
    if result.error_code:
        print(f"error_code: {result.error_code}")


def _prompt_operation_help(registry: Mapping[str, OperationSpec]) -> None:
    op_id = prompt_text("Operation id", "").strip()
    spec = registry.get(op_id)
    if spec is None:
        print("error_code: unknown_operation")
        return
    render_output(help_components(spec), title="Operation help")


def build_operator_menu(
    session: ClientSession,
    registry: Mapping[str, OperationSpec] | None = None,
) -> tuple[MenuAction | MenuSeparator, ...]:
    """Build the menu; requirement-gated rows stay listed, availability hides."""
    specs = REGISTRY if registry is None else registry
    actions: list[MenuAction | MenuSeparator] = [MenuSeparator("Operations")]
    for spec in specs.values():
        if spec.available is None or spec.available(session):
            actions.append(
                menu_action(
                    spec.label,
                    lambda spec=spec, session=session: _run_and_render(spec, session),
                )
            )
    actions.append(MenuSeparator("Discovery"))
    actions.append(
        menu_action(
            "List operations",
            lambda: render_output(listing_components(specs), title="Operations"),
        )
    )
    actions.append(menu_action("Operation help", lambda: _prompt_operation_help(specs)))
    return build_menu(*actions)


def _print_result(result: OpResult, json_output: bool) -> int:
    if json_output:
        print(json.dumps(result.to_payload(), indent=2))
    else:
        if result.components:
            render_output(result.components, title=result.title)
        if result.error_code:
            print(f"error_code: {result.error_code}")
    return 1 if result.error_code else 0


def _argv_operation(rest: list[str], session: ClientSession) -> int:
    json_output = "--json" in rest
    if not rest or rest[0] in ("--json", "--help", "--options"):
        result = _error_result(
            "object", "invalid_options", "", "an operation id is required"
        )
        return _print_result(result, json_output)
    op_id, tokens = rest[0], rest[1:]
    spec = REGISTRY.get(op_id)
    kind = spec.result_kind if spec is not None else "object"
    if "--help" in tokens or "-h" in tokens:
        if spec is None:
            result = _error_result(
                kind, "unknown_operation", op_id, f"unknown operation: {op_id}"
            )
            return _print_result(result, json_output)
        if json_output:
            print(json.dumps(operation_help(spec), indent=2))
        else:
            render_output(help_components(spec), title="Operation help")
        return 0
    raw_options: dict[str, Any] | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--json":
            index += 1
        elif token == "--options":
            if index + 1 >= len(tokens):
                result = _error_result(
                    kind, "invalid_options", op_id, "--options needs a JSON value"
                )
                return _print_result(result, json_output)
            try:
                decoded = json.loads(tokens[index + 1])
            except json.JSONDecodeError as exc:
                result = _error_result(kind, "invalid_options", op_id, str(exc))
                return _print_result(result, json_output)
            if not isinstance(decoded, dict):
                result = _error_result(
                    kind, "invalid_options", op_id, "--options must be a JSON object"
                )
                return _print_result(result, json_output)
            raw_options = decoded
            index += 2
        else:
            result = _error_result(
                kind, "invalid_options", op_id, f"unknown argument: {token}"
            )
            return _print_result(result, json_output)
    return _print_result(execute_by_id(op_id, session, raw_options), json_output)


def _argv_dispatch(argv: list[str], session: ClientSession) -> int:
    args = list(argv)
    if args[0] == "--config":
        from edgar_sec.apps.client.operator_config import run_config_argv

        return run_config_argv(args[1:], session)
    if args[0] == "--list-operations":
        rest = args[1:]
        if any(token != "--json" for token in rest):
            result = _error_result(
                "object", "invalid_options", "", "only --json may follow"
            )
            return _print_result(result, "--json" in rest)
        if "--json" in rest:
            print(json.dumps(operation_listing(REGISTRY), indent=2))
        else:
            render_output(listing_components(REGISTRY), title="Operations")
        return 0
    if args[0] == "--op":
        return _argv_operation(args[1:], session)
    return cli.main(args)


def _startup_error() -> str | None:
    """One clear startup refusal, or None when the run may proceed.
    The workspace must resolve and the shipped package data must be present
    at its self-located anchor; either failure is reported once, here.
    """
    from edgar_sec.foundation.runtime.paths import (
        ProjectRootError,
        package_data_status,
        resolve_paths,
    )

    try:
        resolve_paths()
    except ProjectRootError as exc:
        return (
            f"{exc} Name the workspace with the workspace.root setting "
            "(WORKSPACE_ROOT) or run from a directory outside the package."
        )
    status = package_data_status()
    if not status.present:
        return (
            "package data is missing: no taxonomy tree at "
            f"{status.taxonomy_dir} (archive present: {status.archive_dir_present}). "
            "This install is broken; reinstall the package."
        )
    return None


def main(argv: list[str] | None = None, *, session: ClientSession | None = None) -> int:
    """Operator entrypoint: menu with no arguments, argv host otherwise."""
    if (error := _startup_error()) is not None:
        print(error, file=sys.stderr)
        return 2
    held = session or ClientSession()
    return operator_entrypoint(
        MENU_TITLE,
        lambda: build_operator_menu(held),
        lambda args: _argv_dispatch(args, held),
        argv,
        interrupted_message=INTERRUPTED_MESSAGE,
        before_menu=lambda: render_session_header(held),
    )


if __name__ == "__main__":
    # runpy re-execution splits module identity, so delegate to the
    # canonically imported module whose OpResult sibling rows build.
    from edgar_sec.apps.client.operator import main as _canonical_main

    sys.exit(_canonical_main())
