"""Fetch, read-context, and snapshot-context rows for the client operator.

Rows contribute through ``register(registry)`` and ``GATHERERS``; operator
imports stay inside functions so this module loads standalone.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.interactive import prompt_confirm, prompt_text
from edgar_sec.foundation.runtime.render import (
    Grid,
    KeyValueRow,
    ProseRow,
    render_output,
)

__all__ = [
    "GATHERERS",
    "SPECS",
    "FetchOptions",
    "LimitOptions",
    "SetReadContextOptions",
    "SnapshotBranchesOptions",
    "SnapshotCheckoutOptions",
    "SnapshotCurrentOptions",
    "build_specs",
    "register",
]


def _f(default: Any, help_text: str):
    return field(default=default, metadata={"help": help_text})


_MODES = ("fast", "pipeline", "snapshot")
_MSG_SEED = "seed refused: no constraining input (tickers, ciks, accessions, forms, or dates); a limit alone is not a constraint"
_SET_HELP = "Target set; empty means the current set (or 'main'). With no seed fields, the fetch is set-driven and reads accessions from this set."
_SEED_HELP = "Seed field (FilingQuery vocabulary); any seed field present makes the fetch seed-driven. Refusal: a seed with no tickers, CIKs, accessions, forms, or dates is refused; a limit alone is not a constraint."
_MODE_HELP = "Engine mode (fast, pipeline, snapshot). When set, it first updates the session read context, then the fetch uses the context's mode; empty leaves the context unchanged. Mode is never inferred from the query shape."
_LIMIT_HELP = "Maximum records shown; total versus shown is declared. Refused below 1."


@dataclass(frozen=True, slots=True)
class SetReadContextOptions:
    """Options for setting the session read context explicitly."""

    mode: str = _f("", _MODE_HELP)
    snapshot: str = _f("", "Snapshot selector (id, tag, or branch); empty leaves it.")


@dataclass(frozen=True, slots=True)
class FetchOptions:
    """Options for the fetch operation: a set drive or a fresh seed."""

    set_name: str = _f("", _SET_HELP)
    tickers: tuple[str, ...] = _f((), _SEED_HELP)
    ciks: tuple[str, ...] = _f((), "Seed CIKs; see tickers for the refusal rule.")
    accessions: tuple[str, ...] = _f((), "Seed accessions; see tickers.")
    forms: tuple[str, ...] = _f((), "Seed forms; forms alone constrain a seed.")
    dates: str | None = _f(None, "Facade date vocabulary; dates alone constrain.")
    roles: tuple[str, ...] = _f(("primary",), "Roles; non-primary runs the pipeline.")
    suffixes: tuple[str, ...] = _f((), "Document suffixes to acquire.")
    operations: tuple[str, ...] = _f((), "Acquisition operations to run per filing.")
    limit: int | None = _f(None, "Caps filings; a limit alone is not a constraint.")
    workers: int | None = _f(None, "Pipeline workers; empty uses the facade's.")
    mode: str = _f("", _MODE_HELP)


@dataclass(frozen=True, slots=True)
class LimitOptions:
    """Options for a bounded listing row."""

    limit: int = _f(20, _LIMIT_HELP)


@dataclass(frozen=True, slots=True)
class SnapshotBranchesOptions:
    """Options for listing snapshot branches."""


@dataclass(frozen=True, slots=True)
class SnapshotCurrentOptions:
    """Options for showing a branch's current snapshot."""

    branch: str = _f("main", "Branch whose tip snapshot is shown.")


@dataclass(frozen=True, slots=True)
class SnapshotCheckoutOptions:
    """Options for checking out a snapshot position."""

    selector: str = _f(
        "",
        "Snapshot id or tag; it becomes the session's snapshot position for snapshot-mode reads and snapshot seeds. Unknown selectors are not_found and the position does not move.",
    )


def _key_value(title: str, data: dict, rows: Iterable[tuple[str, str]], **extra: Any):
    from edgar_sec.apps.client.operator import OpResult

    components = tuple(KeyValueRow(k, v) for k, v in rows)
    return OpResult(
        kind="key_value",
        title=title,
        components=components,
        data=data,
        total=len(components),
        shown=len(components),
        **extra,
    )


def _error(kind: str, code: str, title: str, message: str, data: dict | None = None):
    from edgar_sec.apps.client.operator import OpResult

    return OpResult(
        kind=kind,
        title=title,
        components=(ProseRow(message),),
        data={**(data or {}), "message": message},
        error_code=code,
    )


def _absent(kind: str, title: str, message: str, data: dict):
    return _error(kind, "absent", title, message, {**data, "present": False})


def _json_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_native(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _has_seed(options: FetchOptions) -> bool:
    return bool(
        options.tickers
        or options.ciks
        or options.accessions
        or options.forms
        or options.dates
    )


def _seed_fields(options: FetchOptions) -> dict[str, Any]:
    names = (
        "tickers",
        "ciks",
        "accessions",
        "forms",
        "roles",
        "suffixes",
        "operations",
    )
    fields = {name: list(getattr(options, name)) for name in names}
    fields.update(dates=options.dates, limit=options.limit, workers=options.workers)
    return fields


def _run_fetch(
    session: Any,
    options: FetchOptions,
    *,
    operation_id: str,
    selection_override: dict[str, Any] | None = None,
    rerun_of: str = "",
):
    from edgar_sec.apps.client import operator_run_records as records

    title = "Fetch filings"
    if options.mode:
        if options.mode not in _MODES:
            return _error(
                "key_value", "invalid_options", title, f"unknown mode: {options.mode}"
            )
        session.read_context.mode = options.mode
    if options.limit is not None and options.limit < 1:
        return _error("key_value", "invalid_options", title, "limit below 1")
    if options.workers is not None and options.workers < 1:
        return _error("key_value", "invalid_options", title, "workers below 1")
    context = session.read_context
    requested: list[str] | None = None
    if selection_override is not None:
        requested = [str(a) for a in selection_override.get("accessions", [])]
        selection = _json_native(selection_override)
        drive: dict[str, Any] = {"accessions": tuple(requested)}
    elif _has_seed(options):
        selection = {"kind": "seed", "seed": _seed_fields(options)}
        drive = {
            "tickers": tuple(options.tickers),
            "ciks": tuple(options.ciks),
            "accessions": tuple(options.accessions),
            "forms": tuple(options.forms),
            "dates": options.dates,
        }
    else:
        name = options.set_name or session.current_set_name
        working = session.sets.get(name) if name else None
        if working is None:
            if options.set_name:
                return _error(
                    "key_value",
                    "not_found",
                    title,
                    f"set not found: {options.set_name}",
                )
            return _error("key_value", "refused", title, _MSG_SEED)
        if not working.accessions:
            return _error("key_value", "refused", title, _MSG_SEED)
        requested = sorted(working.accessions)
        selection = {"kind": "set", "set_name": name, "accessions": requested}
        drive = {"accessions": tuple(requested)}
    target = options.set_name or session.current_set_name or "main"
    if selection.get("kind") == "set":
        target = str(selection.get("set_name") or target)
    started = datetime.now(UTC)
    cache_before = records.cache_stats(session)
    fetch_kwargs: dict[str, Any] = {
        "tickers": (),
        "ciks": (),
        "accessions": (),
        "forms": (),
        "dates": None,
        **drive,
        "suffixes": tuple(options.suffixes),
        "roles": tuple(options.roles),
        "limit": options.limit,
        "operations": tuple(options.operations),
        "mode": context.mode,
        "snapshot": context.snapshot,
        "workers": options.workers,
    }
    record_id = f"op-{started.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    base_record: dict[str, Any] = {
        "record_id": record_id,
        "operation": operation_id,
        "started_at": started.isoformat(),
        "options": _json_native(asdict(options)),
        "selection": selection,
        "mode": context.mode,
        "snapshot": context.snapshot,
    }
    if rerun_of:
        base_record["rerun_of"] = rerun_of
    try:
        result = session.facade.fetch(**fetch_kwargs)
    except Exception as exc:  # noqa: BLE001 - a facade failure is a coded result
        engine = records.engine_taken(
            context.mode, tuple(options.roles), tuple(drive.get("accessions", ())), None
        )
        accounting = {
            "source": "facade call raised before any result",
            "success_count": 0,
            "successes": [],
            "error_count": 0,
            "errors": [],
            "other_count": 0,
        }
        records.finish_record(
            session,
            base_record,
            engine=engine,
            cache=records.cache_line(cache_before, records.cache_stats(session)),
            table_counts={},
            member_accounting=accounting,
            result={"run_id": "", "plan_id": "", "accession_count": 0},
            error_code="external_failure",
            error=str(exc),
        )
        data = {"record_id": record_id, "engine": engine, "message": str(exc)}
        return _error("key_value", "external_failure", title, str(exc), data)
    from edgar_sec.apps.client.operator_selection import (
        result_accessions,
        store_working_set,
    )

    returned = result_accessions(result)
    counts = records.table_counts(result)
    accounting = records.member_accounting(
        returned, records.payload_rows(result), requested
    )
    engine = records.engine_taken(
        context.mode, tuple(options.roles), tuple(drive.get("accessions", ())), result
    )
    cache = records.cache_line(cache_before, records.cache_stats(session))
    working = store_working_set(session, target, result=result)
    result_info = {
        "run_id": str(getattr(result, "run_id", "") or ""),
        "plan_id": str(getattr(result, "plan_id", "") or ""),
        "accession_count": len(returned),
    }
    path = records.finish_record(
        session,
        base_record,
        engine=engine,
        cache=cache,
        table_counts=counts,
        member_accounting=accounting,
        result=result_info,
        error_code=None,
        error=None,
    )
    data = {
        "set": target,
        "count": len(working),
        "engine": engine,
        "mode": context.mode,
        "snapshot": context.snapshot,
        "run_id": result_info["run_id"],
        "plan_id": result_info["plan_id"],
        "table_counts": counts,
        "member_accounting": accounting,
        "cache": cache,
        "record_id": record_id,
        "record_path": str(path),
    }
    rows = (
        ("set", target),
        ("count", str(len(working))),
        ("engine", engine),
        ("mode", context.mode),
        ("snapshot", context.snapshot or "none"),
        ("run", result_info["run_id"] or "none"),
        ("successes", str(accounting["success_count"])),
        ("member errors", str(accounting["error_count"])),
        ("cache", "measured" if cache is not None else "unavailable"),
        ("record", record_id),
    )
    return _key_value(title, data, rows, hints=("peek", "inspect_past_run", "vars"))


def _fetch(options: FetchOptions, session: Any):
    return _run_fetch(session, options, operation_id="fetch")


def _set_context(options: SetReadContextOptions, session: Any):
    title = "Set read context"
    if options.mode and options.mode not in _MODES:
        return _error(
            "key_value", "invalid_options", title, f"unknown mode: {options.mode}"
        )
    if options.mode:
        session.read_context.mode = options.mode
    if options.snapshot:
        session.read_context.snapshot = options.snapshot
    context = session.read_context
    data = {"mode": context.mode, "snapshot": context.snapshot}
    rows = (("mode", context.mode), ("snapshot", context.snapshot or "none"))
    return _key_value(title, data, rows, hints=("fetch", "seed_snapshot"))


def _console(session: Any) -> Any:
    console = session.facade.snapshots
    return console() if callable(console) else console


def _snapshot_grid(title: str, message: str, data: dict, headers, rows, total: int):
    from edgar_sec.apps.client.operator import OpResult

    if total == 0:
        return _absent("grid", title, message, data)
    return OpResult(
        kind="grid",
        title=title,
        components=(Grid(headers=headers, rows=rows),),
        data={**data, "present": True},
        total=total,
        shown=len(rows),
        hints=("snapshot_checkout",),
    )


def _console_grid(session: Any, options: LimitOptions, which: str):
    title, message = (
        ("Snapshots", "no snapshots in the store")
        if which == "list"
        else ("Snapshot tags", "no snapshot tags in the store")
    )
    if options.limit < 1:
        return _error("grid", "invalid_options", title, "limit below 1")
    items = getattr(_console(session), which)()
    shown = items[: options.limit]
    key = "snapshot_id" if which == "list" else "name"
    field = "kind" if which == "list" else "snapshot_id"
    rows = tuple(
        (str(i.get(key, "")), str(i.get(field, "")), str(i.get("created_at", "")))
        for i in shown
    )
    data = {
        "snapshots" if which == "list" else "tags": [_json_native(i) for i in shown]
    }
    headers = (
        ("snapshot", "kind", "created")
        if which == "list"
        else ("tag", "snapshot", "created")
    )
    return _snapshot_grid(title, message, data, headers, rows, len(items))


def _snapshots(options: LimitOptions, session: Any):
    return _console_grid(session, options, "list")


def _tags(options: LimitOptions, session: Any):
    return _console_grid(session, options, "tags")


def _branches(options: SnapshotBranchesOptions, session: Any):
    items = sorted(_console(session).branches().items())
    rows = tuple((str(name), str(tip)) for name, tip in items)
    data = {"branches": {str(k): str(v) for k, v in items}}
    return _snapshot_grid(
        "Snapshot branches",
        "no snapshot branches in the store",
        data,
        ("branch", "snapshot"),
        rows,
        len(items),
    )


def _current(options: SnapshotCurrentOptions, session: Any):
    title = "Current snapshot"
    current = _console(session).current(options.branch)
    if not current:
        return _absent(
            "key_value",
            title,
            f"branch {options.branch} has no current snapshot",
            {"branch": options.branch, "snapshot": None},
        )
    data = {"branch": options.branch, "snapshot": str(current), "present": True}
    rows = (("branch", options.branch), ("snapshot", str(current)))
    return _key_value(title, data, rows, hints=("snapshot_checkout",))


def _known_selectors(console: Any) -> set[str]:
    known: set[str] = set()
    for item in console.list():
        if item.get("snapshot_id"):
            known.add(str(item["snapshot_id"]))
    for item in console.tags():
        if item.get("name"):
            known.add(str(item["name"]))
        if item.get("snapshot_id"):
            known.add(str(item["snapshot_id"]))
    for name, tip in console.branches().items():
        known.update((str(name), str(tip)))
    if console.current():
        known.add(str(console.current()))
    return known


def _checkout(options: SnapshotCheckoutOptions, session: Any):
    title = "Snapshot checkout"
    selector = options.selector.strip()
    if not selector:
        return _error(
            "key_value", "invalid_options", title, "a snapshot selector is required"
        )
    if selector not in _known_selectors(_console(session)):
        return _error(
            "key_value", "not_found", title, f"snapshot not found: {selector}"
        )
    session.read_context.snapshot = selector
    data = {"snapshot": selector, "mode": session.read_context.mode}
    rows = (("snapshot", selector), ("mode", session.read_context.mode))
    return _key_value(title, data, rows, hints=("seed_snapshot", "fetch"))


def build_specs() -> tuple:
    """Build this module's registry rows; operator imports resolve at call time."""
    from edgar_sec.apps.client.operator import OperationSpec

    def spec(op_id, label, options_type, effect, kind, executor):
        return OperationSpec(
            id=op_id,
            label=label,
            options_type=options_type,
            effect=effect,
            requires="none",
            result_kind=kind,
            hints=("session_summary",),
            executor=executor,
        )

    return (
        spec(
            "set_read_context",
            "Set read context",
            SetReadContextOptions,
            "moves_position",
            "key_value",
            _set_context,
        ),
        spec("fetch", "Fetch filings", FetchOptions, "external", "key_value", _fetch),
        spec(
            "snapshot_list",
            "List snapshots",
            LimitOptions,
            "reads_state",
            "grid",
            _snapshots,
        ),
        spec(
            "snapshot_tags",
            "List snapshot tags",
            LimitOptions,
            "reads_state",
            "grid",
            _tags,
        ),
        spec(
            "snapshot_branches",
            "List snapshot branches",
            SnapshotBranchesOptions,
            "reads_state",
            "grid",
            _branches,
        ),
        spec(
            "snapshot_current",
            "Current snapshot",
            SnapshotCurrentOptions,
            "reads_state",
            "key_value",
            _current,
        ),
        spec(
            "snapshot_checkout",
            "Check out a snapshot",
            SnapshotCheckoutOptions,
            "moves_position",
            "key_value",
            _checkout,
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


def _split(raw: str) -> tuple[str, ...]:
    return tuple(raw.replace(",", " ").split())


def _gather_fetch(session: Any) -> FetchOptions:
    """Prompt the fetch selection, echo its resolved form, and confirm it."""
    current = str(getattr(session, "current_set_name", "") or "")
    set_name = prompt_text("set name", current).strip()
    tickers = _split(prompt_text("tickers", ""))
    ciks = _split(prompt_text("ciks", ""))
    accessions = _split(prompt_text("accessions", ""))
    forms = _split(prompt_text("forms", ""))
    roles = _split(
        prompt_text("roles (non-primary roles run the pipeline engine)", "primary")
    )
    suffixes = _split(prompt_text("suffixes", ""))
    operations = _split(prompt_text("operations", ""))
    dates_raw = prompt_text("dates", "").strip() or None
    mode = prompt_text("mode", "").strip()
    limit_raw = prompt_text("limit", "20").strip()
    if limit_raw.lower() in ("none", "unbounded", "clear", "-"):
        limit = (
            None if prompt_confirm("fetch with no limit (unbounded)?", False) else 20
        )
    else:
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 20
    workers_raw = prompt_text("workers", "").strip()
    workers = int(workers_raw) if workers_raw.isdigit() else None
    from edgar_sec.apps.runner.config import FilingQuery

    query = FilingQuery(
        tickers=tickers,
        ciks=ciks,
        accessions=accessions,
        forms=forms,
        dates=dates_raw,
        roles=roles or ("primary",),
        suffixes=suffixes,
        limit=limit,
        operations=operations or ("raw",),
    )
    pairs = (
        ("set", set_name or current or "main"),
        ("tickers", ", ".join(tickers) or "none"),
        ("ciks", ", ".join(ciks) or "none"),
        ("accessions", ", ".join(accessions) or "none"),
        ("forms", ", ".join(forms) or "none"),
        ("roles", ", ".join(query.roles)),
        ("suffixes", ", ".join(suffixes) or "none"),
        ("operations", ", ".join(query.operations)),
        ("dates", dates_raw or "none"),
        ("dates resolved", query.resolved_date_string() or "none"),
        ("limit", "unbounded" if limit is None else str(limit)),
        ("mode", mode or session.read_context.mode),
    )
    render_output(
        tuple(KeyValueRow(k, v) for k, v in pairs), title="Resolved fetch selection"
    )
    if not prompt_confirm("run this fetch?", False):
        raise RuntimeError("fetch not confirmed; no run executed")
    return FetchOptions(
        set_name=set_name,
        tickers=tickers,
        ciks=ciks,
        accessions=accessions,
        forms=forms,
        dates=dates_raw,
        roles=roles or ("primary",),
        suffixes=suffixes,
        operations=operations,
        limit=limit,
        workers=workers,
        mode=mode,
    )


def _gather_snapshot_checkout(session: Any) -> SnapshotCheckoutOptions:
    return SnapshotCheckoutOptions(selector=prompt_text("selector", "").strip())


GATHERERS: dict[str, Callable[[Any], Any]] = {
    "fetch": _gather_fetch,
    "snapshot_checkout": _gather_snapshot_checkout,
}
