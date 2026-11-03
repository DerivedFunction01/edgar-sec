"""Statement-view driver reports, scored against pinned expectations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.engine.xbrl.review.benchmark import CensusScore

_CLASSIFICATIONS = ("served-faithful", "served-honest", "blocked")


@dataclass(frozen=True, slots=True)
class BlockedCell:
    """One pinned blocked cell: identity, mechanism, recorded disposition."""

    folder: str
    cell: str
    mechanism: str
    disposition: str


@dataclass(frozen=True, slots=True)
class StatementViewExpectations:
    """Pinned driver totals plus the adjudicated blocked-cell record."""

    cells: int
    faithful: int
    honest: int
    blocked: int
    blocked_cells: tuple[BlockedCell, ...] = ()


def _load_expectations() -> StatementViewExpectations:
    """Load the pinned statement-view expectations from their data file."""
    raw = json.loads(
        Path(__file__)
        .with_name("statement_view_expectations.json")
        .read_text(encoding="utf-8")
    )
    totals = raw["totals"]
    return StatementViewExpectations(
        cells=totals["cells"],
        faithful=totals["faithful"],
        honest=totals["honest"],
        blocked=totals["blocked"],
        blocked_cells=tuple(BlockedCell(**row) for row in raw.get("blocked_cells", [])),
    )


STATEMENT_VIEW_EXPECTATIONS: StatementViewExpectations = _load_expectations()


def summarize_driver_report(report: dict[str, Any]) -> dict[str, Any]:
    """Totals and blocked cells of one merged driver report."""
    counts = dict.fromkeys(_CLASSIFICATIONS, 0)
    blocked: list[dict[str, str]] = []
    load_errors: list[str] = []
    cells = 0
    for folder, record in sorted(report.get("filings", {}).items()):
        if "load_error" in record:
            load_errors.append(folder)
            continue
        for name, verdict in sorted(record.get("classification", {}).items()):
            cells += 1
            counts[verdict["classification"]] += 1
            if verdict["classification"] == "blocked":
                blocked.append(
                    {
                        "folder": folder,
                        "cell": name,
                        "mechanism": verdict["mechanism"] or "",
                    }
                )
    return {
        "cells": cells,
        "faithful": counts["served-faithful"],
        "honest": counts["served-honest"],
        "blocked": counts["blocked"],
        "blocked_cells": blocked,
        "load_errors": load_errors,
    }


def score_statement_views(
    report: dict[str, Any],
    expectations: StatementViewExpectations = STATEMENT_VIEW_EXPECTATIONS,
) -> CensusScore:
    """Score a driver report; any unadjudicated movement fails."""
    summary = summarize_driver_report(report)
    failures: list[str] = []
    for folder in summary["load_errors"]:
        failures.append(f"filing {folder}: failed to load")
    for field in ("cells", "faithful", "honest", "blocked"):
        if summary[field] != getattr(expectations, field):
            failures.append(
                f"totals: {field} {summary[field]} != expected {getattr(expectations, field)}"
            )
    actual = {
        (row["folder"], row["cell"], row["mechanism"])
        for row in summary["blocked_cells"]
    }
    pinned = {
        (row.folder, row.cell, row.mechanism) for row in expectations.blocked_cells
    }
    for folder, cell, mechanism in sorted(actual - pinned):
        failures.append(f"blocked {folder} {cell} ({mechanism}): not pinned")
    for folder, cell, mechanism in sorted(pinned - actual):
        failures.append(f"blocked {folder} {cell} ({mechanism}): pinned but absent")
    return CensusScore(passed=not failures, failures=tuple(failures))
