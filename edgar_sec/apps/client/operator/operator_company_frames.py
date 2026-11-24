"""The frames cross-check row, in explicit frame coordinates.

SEC frame aggregates are recorded as an external run and rendered as
a labelled grid; an empty frame is an honest absence.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from edgar_sec.apps.client.operator.operator_tools import (
    empty_accounting,
    error_result,
    record_external_run,
)
from edgar_sec.foundation.runtime.render import Grid, ProseRow

if TYPE_CHECKING:
    from edgar_sec.apps.client.operator.operator_company import FramesOptions


def _execute_frames(options: FramesOptions, session: Any):
    from edgar_sec.apps.client.operator import operator_run_records as records
    from edgar_sec.apps.client.operator.operator_execution import OpResult

    title = (
        f"Frames cross-check: {options.taxonomy}:{options.tag} "
        f"({options.unit}, {options.period})"
    )
    if not (options.taxonomy and options.tag and options.unit and options.period):
        return error_result(
            "grid",
            "invalid_options",
            title,
            "frames needs explicit taxonomy, tag, unit, and period coordinates",
        )
    if options.limit < 1:
        return error_result("grid", "invalid_options", title, "limit below 1")
    started = datetime.now(UTC)
    cache_before = records.cache_stats(session)
    selection = {
        "kind": "frame",
        "taxonomy": options.taxonomy,
        "tag": options.tag,
        "unit": options.unit,
        "period": options.period,
    }
    try:
        result = session.facade.frames(
            options.taxonomy, options.tag, options.unit, options.period
        )
    except Exception as exc:  # noqa: BLE001 - a facade failure is a coded result
        record_id, _ = record_external_run(
            session,
            operation="frames",
            options_data=asdict(options),
            selection=selection,
            started=started,
            cache_before=cache_before,
            engine="frames",
            result_info={"label": "", "row_count": 0},
            accounting=empty_accounting("facade call raised before any result"),
            error_code="external_failure",
            error=str(exc),
        )
        return error_result(
            "grid", "external_failure", title, str(exc), {"record_id": record_id}
        )
    all_rows = [
        {
            "cik": int(row.cik),
            "entity_name": str(row.entity_name),
            "value": row.value,
            "end": str(row.end),
        }
        for row in result.rows
    ]
    accounting = records.member_accounting([str(r["cik"]) for r in all_rows], None)
    record_id, _ = record_external_run(
        session,
        operation="frames",
        options_data=asdict(options),
        selection=selection,
        started=started,
        cache_before=cache_before,
        engine="frames",
        result_info={"label": str(result.label), "row_count": len(all_rows)},
        accounting=accounting,
    )
    shown = all_rows[: options.limit]
    data = {
        "cross_check": True,
        "provenance": "SEC frame aggregates",
        "frame": {
            "taxonomy": options.taxonomy,
            "tag": options.tag,
            "unit": options.unit,
            "period": options.period,
        },
        "label": str(result.label),
        "rows": shown,
        "record_id": record_id,
        "present": bool(all_rows),
    }
    if not all_rows:
        return OpResult(
            kind="grid",
            title=title,
            components=(ProseRow("frame absent: the SEC frame has no rows"),),
            data=data,
            total=0,
            shown=0,
            error_code="absent",
            hints=("company_concept",),
        )
    grid = Grid(
        headers=("cik", "entity", "value", "end"),
        rows=tuple(
            (str(r["cik"]), r["entity_name"], str(r["value"]), r["end"]) for r in shown
        ),
    )
    return OpResult(
        kind="grid",
        title=title,
        components=(grid,),
        data=data,
        total=len(all_rows),
        shown=len(shown),
        hints=("company_concept",),
    )
