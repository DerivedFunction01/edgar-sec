"""Fund series/class rows for the client operator.

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
from edgar_sec.foundation.runtime.render import KeyValueRow, ProseRow

__all__ = [
    "GATHERERS",
    "SPECS",
    "FundSeriesClassOptions",
    "build_specs",
    "register",
]

_ACTIONS = ("refresh", "reconcile", "status")
_TITLE = "Fund series/class"


def _f(default: Any, help_text: str):
    return field(default=default, metadata={"help": help_text})


@dataclass(frozen=True, slots=True)
class FundSeriesClassOptions:
    """Options for the fund series/class row: one row, three actions."""

    action: str = _f(
        "status",
        "Action: refresh fetches, ingests, and publishes; reconcile counts "
        "the stored layers; status shows the tip and layer counts. The row "
        "is external because refresh is; run records are written for "
        "refresh only.",
    )
    branch: str = _f(
        "main", "DAG branch a refresh publishes to and status reads the tip of."
    )
    ciks: tuple[str, ...] = _f(
        (),
        "Refresh scope: these CIKs only; empty means the full ticker-file "
        "population. Ignored by reconcile and status.",
    )
    force_refresh: bool = _f(
        False,
        "Bypass the response cache on every fetch of a refresh. Ignored by "
        "reconcile and status.",
    )
    workers: int | None = _f(
        None,
        "Worker count; empty uses the session's. Fetches stay sequential "
        "through the one client, so this never multiplies HTTP clients. "
        "Refused below 1.",
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


def _json_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_native(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _artifacts_root(session: Any) -> Path:
    root = getattr(session.facade, "artifacts_root", None)
    if root:
        return Path(root)
    from edgar_sec.foundation.runtime.paths import resolve_paths

    return resolve_paths().artifacts_root


def _reconciliation_data(counts: Any) -> dict[str, int]:
    return {
        "series_in_both": counts.series_in_both,
        "series_browse_only": counts.series_browse_only,
        "series_file_only": counts.series_file_only,
        "classes_in_both": counts.classes_in_both,
        "classes_browse_only": counts.classes_browse_only,
        "classes_file_only": counts.classes_file_only,
        "symbol_agreements": counts.symbol_agreements,
        "symbol_disagreements": counts.symbol_disagreements,
        "shared_classes_browse_untickered": (counts.shared_classes_browse_untickered),
    }


def _refresh(options: FundSeriesClassOptions, session: Any):
    from edgar_sec.apps.client import operator_run_records as records
    from edgar_sec.pipelines.metadata_sync.commands.series_class import (
        refresh_series_class,
    )

    title = f"{_TITLE} refresh"
    if options.workers is not None and options.workers < 1:
        return _error("key_value", "invalid_options", title, "workers below 1")
    started = datetime.now(UTC)
    record_id = f"op-{started.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    base_record: dict[str, Any] = {
        "record_id": record_id,
        "operation": "fund_series_class",
        "started_at": started.isoformat(),
        "options": _json_native(asdict(options)),
    }
    workers = (
        options.workers
        if options.workers is not None
        else getattr(session, "workers", None)
    )
    try:
        outcome = refresh_series_class(
            artifacts_root=_artifacts_root(session),
            branch=options.branch,
            ciks=tuple(options.ciks),
            force_refresh=options.force_refresh,
            workers=workers,
        )
    except Exception as exc:  # noqa: BLE001 - a drive failure is a coded result
        records.finish_record(
            session,
            base_record,
            publish={"published": False, "snapshot_id": None},
            error_code="external_failure",
            error=str(exc),
        )
        data = {"record_id": record_id, "message": str(exc)}
        return _error("key_value", "external_failure", title, str(exc), data)
    publish = {
        "published": outcome.publish.published,
        "snapshot_id": outcome.publish.snapshot_id,
        "tip_before": outcome.publish.tip_before,
        "tip_after": outcome.tip_after,
    }
    accounting = {
        "population": outcome.population,
        "parsed_ingested": outcome.parsed_ingested,
        "parse_failures": outcome.parse_failures,
        "unrecognized": outcome.unrecognized,
        "fetch_failures": outcome.fetch_failures,
        "failure_samples": [list(pair) for pair in outcome.failure_samples],
        "symbol_disagreement_samples": [
            list(sample) for sample in outcome.symbol_disagreement_samples
        ],
    }
    reconciliation = _reconciliation_data(outcome.reconciliation)
    path = records.finish_record(
        session,
        base_record,
        publish=publish,
        reconciliation=reconciliation,
        accounting=accounting,
        error_code=None,
        error=None,
    )
    data = {
        "action": "refresh",
        **publish,
        "reconciliation": reconciliation,
        "accounting": accounting,
        "record_id": record_id,
        "record_path": str(path),
    }
    rows = (
        ("published", str(publish["published"])),
        ("snapshot", publish["snapshot_id"] or "none"),
        ("tip before", publish["tip_before"] or "none"),
        ("tip after", publish["tip_after"] or "none"),
        ("population", str(outcome.population)),
        ("parsed + ingested", str(outcome.parsed_ingested)),
        ("parse failures", str(outcome.parse_failures)),
        ("unrecognized", str(outcome.unrecognized)),
        ("fetch failures", str(outcome.fetch_failures)),
        ("symbol disagreements", str(reconciliation["symbol_disagreements"])),
        ("record", record_id),
    )
    return _key_value(title, data, rows, hints=("session_summary",))


def _reconcile(options: FundSeriesClassOptions, session: Any):
    from edgar_sec.pipelines.metadata_sync.commands.series_class import (
        read_series_class_reconciliation,
    )

    counts = read_series_class_reconciliation(artifacts_root=_artifacts_root(session))
    reconciliation = _reconciliation_data(counts)
    data = {"action": "reconcile", "reconciliation": reconciliation}
    rows = tuple(
        (name.replace("_", " "), str(value)) for name, value in reconciliation.items()
    )
    return _key_value(f"{_TITLE} reconcile", data, rows, hints=("session_summary",))


def _status(options: FundSeriesClassOptions, session: Any):
    from edgar_sec.pipelines.metadata_sync.commands.series_class import (
        read_series_class_status,
    )

    status = read_series_class_status(
        artifacts_root=_artifacts_root(session), branch=options.branch
    )
    data = {
        "action": "status",
        "branch": options.branch,
        "tip": status.tip,
        "tickered_rows": status.tickered_rows,
        "browse_class_rows": status.browse_class_rows,
        "browse_series_rows": status.browse_series_rows,
    }
    rows = (
        ("branch", options.branch),
        ("tip", status.tip or "none"),
        ("tickered rows", str(status.tickered_rows)),
        ("browse class rows", str(status.browse_class_rows)),
        ("browse series rows", str(status.browse_series_rows)),
    )
    return _key_value(f"{_TITLE} status", data, rows, hints=("session_summary",))


def _execute(options: FundSeriesClassOptions, session: Any):
    if options.action not in _ACTIONS:
        return _error(
            "key_value",
            "invalid_options",
            _TITLE,
            f"unknown action: {options.action}",
        )
    if options.action == "refresh":
        return _refresh(options, session)
    if options.action == "reconcile":
        return _reconcile(options, session)
    return _status(options, session)


def build_specs() -> tuple:
    """Build this module's registry rows; operator imports resolve at call time."""
    from edgar_sec.apps.client.operator import OperationSpec

    return (
        OperationSpec(
            id="fund_series_class",
            label="Fund series/class",
            options_type=FundSeriesClassOptions,
            effect="external",
            requires="none",
            result_kind="key_value",
            hints=("session_summary",),
            executor=_execute,
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


def _gather_fund_series_class(session: Any) -> FundSeriesClassOptions:
    """Prompt the fund series/class action and its refresh scope."""
    action = prompt_text("action (refresh, reconcile, status)", "status").strip()
    branch = prompt_text("branch", "main").strip() or "main"
    ciks = _split(prompt_text("ciks (refresh scope; empty = full population)", ""))
    force = prompt_confirm("force refresh (bypass the response cache)?", False)
    return FundSeriesClassOptions(
        action=action or "status",
        branch=branch,
        ciks=ciks,
        force_refresh=force,
    )


GATHERERS: dict[str, Callable[[Any], Any]] = {
    "fund_series_class": _gather_fund_series_class,
}
