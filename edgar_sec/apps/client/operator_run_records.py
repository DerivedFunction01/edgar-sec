"""Run-record machinery and past-runs rows for the client operator.

Records for external rows live as canonical JSON manifests in a dedicated
operator-runs area; discovery scans that area only, never a store.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.render import Grid
from edgar_sec.infra.storage.atomic import atomic_write_json

__all__ = [
    "GATHERERS",
    "SPECS",
    "RecordOptions",
    "build_specs",
    "cache_line",
    "cache_stats",
    "engine_taken",
    "finish_record",
    "list_records",
    "member_accounting",
    "operator_runs_root",
    "payload_rows",
    "read_run_record",
    "register",
    "table_counts",
]

_FAILURE_OUTCOMES = frozenset(
    {"failed", "not_filed", "required_missing", "ambiguous", "blocked", "unsupported"}
)


@dataclass(frozen=True, slots=True)
class RecordOptions:
    """Options naming one run record."""

    record_id: str = field(
        default="",
        metadata={"help": "Record id; empty means the session's last run record."},
    )


def _artifacts_root(session: Any) -> Path:
    root = getattr(session.facade, "artifacts_root", None)
    if root:
        return Path(root)
    from edgar_sec.foundation.runtime.paths import resolve_paths

    return resolve_paths().artifacts_root


def operator_runs_root(session: Any) -> Path:
    """The dedicated operator-runs area under the client's artifacts root."""
    return _artifacts_root(session) / "operator-runs"


def read_run_record(session: Any, record_id: str) -> dict[str, Any] | None:
    """One stored run record by id, or None; discovery is manifest-only."""
    if not record_id or "/" in record_id or "\\" in record_id or ".." in record_id:
        return None
    path = operator_runs_root(session) / f"{record_id}.json"
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def list_records(session: Any) -> list[dict[str, Any]]:
    """Every readable run record, newest first, from the manifests alone."""
    root = operator_runs_root(session)
    records: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(record, dict) and record.get("record_id"):
                records.append(record)
    records.sort(
        key=lambda r: (str(r.get("started_at", "")), str(r.get("record_id", ""))),
        reverse=True,
    )
    return records


def finish_record(session: Any, base: dict, **fields: Any) -> Path:
    """Stamp, atomically write, and reference one run record."""
    record = {**base, "finished_at": datetime.now(UTC).isoformat(), **fields}
    root = operator_runs_root(session)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{record['record_id']}.json"
    atomic_write_json(path, record)
    session.last_run_record = str(record["record_id"])
    return path


def cache_stats(session: Any) -> dict[str, Any] | None:
    """The facade's cache stats, or None when it cannot report them."""
    try:
        stats = session.facade.cache_stats()
    except Exception:  # noqa: BLE001 - a stats failure reads as honest absence
        return None
    return stats if isinstance(stats, dict) else None


def _numeric_leaves(value: Any, prefix: str = "") -> dict[str, float]:
    leaves: dict[str, float] = {}
    if isinstance(value, dict):
        for key in sorted(value):
            leaves.update(_numeric_leaves(value[key], f"{prefix}{key}."))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        leaves[prefix.rstrip(".")] = value
    return leaves


def cache_line(before: dict | None, after: dict | None) -> dict | None:
    """Cache-stats deltas across a run; None when either side is absent."""
    if before is None or after is None:
        return None
    flat_before, flat_after = _numeric_leaves(before), _numeric_leaves(after)
    delta = {
        k: flat_after.get(k, 0) - flat_before.get(k, 0)
        for k in sorted(set(flat_before) | set(flat_after))
        if flat_after.get(k, 0) - flat_before.get(k, 0) != 0
    }
    return {"before": flat_before, "after": flat_after, "delta": delta}


def payload_rows(result: Any) -> list[dict[str, Any]] | None:
    """Payload (staged) table rows: the result's per-member status channel."""
    staged = getattr(result, "staged_df", None)
    if not callable(staged):
        return None
    try:
        frame = staged()
    except Exception:  # noqa: BLE001 - the payload table may be unavailable
        return None
    return [
        {"accession": str(r.get("accession", "")), "outcome": str(r.get("outcome", ""))}
        for r in frame.to_dict("records")
    ]


_TABLE_ACCESSORS = (
    ("catalog", "to_arrow", lambda r: int(r.to_arrow().num_rows)),
    ("index", "attachments_df", lambda r: len(r.attachments_df())),
    ("exhibits", "exhibits", lambda r: len(r.exhibits())),
    ("linkbases", "linkbases_df", lambda r: len(r.linkbases_df())),
    ("payload", "staged_df", lambda r: len(r.staged_df())),
    ("joined", "joined_df", lambda r: len(r.joined_df())),
)


def table_counts(result: Any) -> dict[str, int]:
    """Row counts per core result table, via cheap public accessors only."""
    counts: dict[str, int] = {}
    for name, attribute, accessor in _TABLE_ACCESSORS:
        if not callable(getattr(result, attribute, None)):
            continue
        try:
            counts[name] = accessor(result)
        except Exception:  # noqa: BLE001 - an unreadable table is omitted, not faked
            continue
    return counts


def member_accounting(
    result_accessions: Iterable[str],
    payload: list[dict[str, Any]] | None,
    requested: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Success and per-member error accounting from the result's own shape.

    The payload (staged) table is the only per-member status channel on a
    result: accession plus outcome, with no error-detail column.
    """
    returned = frozenset(str(a) for a in result_accessions)
    errors: list[dict[str, str]] = []
    other = 0
    if payload is not None:
        for row in payload:
            if row["outcome"] in _FAILURE_OUTCOMES:
                errors.append(
                    {
                        "accession": row["accession"],
                        "error_code": "external_failure",
                        "outcome": row["outcome"],
                    }
                )
            elif row["outcome"] != "acquired":
                other += 1
    failed = {entry["accession"] for entry in errors}
    if requested is not None:
        for accession in sorted(set(requested) - returned - failed):
            errors.append(
                {
                    "accession": accession,
                    "error_code": "external_failure",
                    "outcome": "not_returned",
                }
            )
    errors.sort(key=lambda entry: entry["accession"])
    successes = returned - failed
    return {
        "source": "payload outcome column plus requested-but-not-returned members",
        "success_count": len(successes),
        "successes": sorted(successes),
        "error_count": len(errors),
        "errors": errors,
        "other_count": other,
    }


def engine_taken(mode: str, roles: tuple, accessions: tuple, result: Any) -> str:
    """The engine actually taken, by the CLI's routing rule and run identity."""
    snapshot = (
        mode == "snapshot"
        or getattr(result, "snapshot_backed", False)
        or getattr(result, "snapshot_id", None)
        or str(getattr(result, "run_id", "") or "").startswith("snapshot-")
    )
    if snapshot:
        return "snapshot"
    if mode == "fast" and tuple(roles) == ("primary",) and not accessions:
        return "fast"
    return "pipeline"


def _record_summary(record: dict) -> dict[str, Any]:
    accounting = record.get("member_accounting") or {}
    return {
        "record_id": str(record.get("record_id", "")),
        "operation": str(record.get("operation", "")),
        "started_at": str(record.get("started_at", "")),
        "engine": str(record.get("engine", "")),
        "success_count": int(accounting.get("success_count", 0)),
        "error_count": int(accounting.get("error_count", 0)),
    }


def _past_runs(options: Any, session: Any):
    from edgar_sec.apps.client.operator import OpResult
    from edgar_sec.apps.client.operator_fetch import _absent, _error

    title = "Past runs"
    if options.limit < 1:
        return _error("grid", "invalid_options", title, "limit below 1")
    records = list_records(session)
    if not records:
        return _absent("grid", title, "no run records recorded yet", {"records": []})
    data_rows = [_record_summary(r) for r in records[: options.limit]]
    grid_rows = tuple(
        (
            r["record_id"],
            r["operation"],
            r["started_at"],
            r["engine"],
            str(r["success_count"]),
            str(r["error_count"]),
        )
        for r in data_rows
    )
    grid = Grid(
        headers=("record", "operation", "started", "engine", "ok", "errors"),
        rows=grid_rows,
    )
    return OpResult(
        kind="grid",
        title=title,
        components=(grid,),
        data={"records": data_rows, "present": True},
        total=len(records),
        shown=len(data_rows),
        hints=("inspect_past_run", "rerun_past_run"),
    )


def _record_rows(record: dict[str, Any]) -> list[tuple[str, str]]:
    accounting = record.get("member_accounting") or {}
    result = record.get("result") or {}
    pairs = (
        ("record", record.get("record_id", "")),
        ("operation", record.get("operation", "")),
        ("started", record.get("started_at", "")),
        ("finished", record.get("finished_at", "")),
        ("engine", record.get("engine", "")),
        ("mode", record.get("mode", "")),
        ("snapshot", record.get("snapshot", "") or "none"),
        ("run", result.get("run_id", "") or "none"),
        ("accessions", result.get("accession_count", 0)),
        ("successes", accounting.get("success_count", 0)),
        ("member errors", accounting.get("error_count", 0)),
        ("cache", "measured" if record.get("cache") is not None else "unavailable"),
        ("error code", record.get("error_code") or "none"),
    )
    rows = [(label, str(value)) for label, value in pairs]
    for entry in accounting.get("errors", []):
        rows.append(
            (f"error {entry.get('accession', '')}", str(entry.get("error_code", "")))
        )
    return rows


def _resolve_record(session: Any, record_id: str) -> tuple[str, dict | None]:
    resolved = record_id or session.last_run_record
    if not resolved:
        return "", None
    return resolved, read_run_record(session, resolved)


def _inspect(options: RecordOptions, session: Any):
    from edgar_sec.apps.client.operator_fetch import _error, _key_value

    title = "Inspect run record"
    resolved, record = _resolve_record(session, options.record_id)
    if record is None:
        return _error(
            "key_value",
            "not_found",
            title,
            f"run record not found: {resolved or '(none)'}",
        )
    return _key_value(title, record, _record_rows(record), hints=("rerun_past_run",))


def _rerun(options: RecordOptions, session: Any):
    from edgar_sec.apps.client.operator import REGISTRY, decode_options
    from edgar_sec.apps.client.operator_fetch import _error, _run_fetch

    title = "Re-run past run"
    resolved, record = _resolve_record(session, options.record_id)
    if record is None:
        return _error(
            "key_value",
            "not_found",
            title,
            f"run record not found: {resolved or '(none)'}",
        )
    try:
        fetch_options = decode_options(REGISTRY["fetch"], record.get("options") or {})
    except (KeyError, ValueError) as exc:
        return _error("key_value", "invalid_options", title, str(exc))
    selection = record.get("selection") or {}
    if selection.get("kind") == "set":
        override = {
            "kind": "set",
            "set_name": selection.get("set_name", ""),
            "accessions": list(selection.get("accessions", [])),
        }
        return _run_fetch(
            session,
            fetch_options,
            operation_id="rerun_past_run",
            selection_override=override,
            rerun_of=resolved,
        )
    return _run_fetch(
        session, fetch_options, operation_id="rerun_past_run", rerun_of=resolved
    )


def build_specs() -> tuple:
    """Build this module's registry rows; operator imports resolve at call time."""
    from edgar_sec.apps.client.operator import OperationSpec
    from edgar_sec.apps.client.operator_fetch import LimitOptions

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
        spec("past_runs", "Past runs", LimitOptions, "reads_state", "grid", _past_runs),
        spec(
            "inspect_past_run",
            "Inspect a past run",
            RecordOptions,
            "reads_state",
            "key_value",
            _inspect,
        ),
        spec(
            "rerun_past_run",
            "Re-run a past run",
            RecordOptions,
            "external",
            "key_value",
            _rerun,
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


GATHERERS: dict[str, Callable[[Any], Any]] = {}
