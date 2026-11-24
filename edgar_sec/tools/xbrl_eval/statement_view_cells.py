"""Per-filing driver cells: raw surface outcomes for one filing."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from edgar_sec.tools.xbrl_eval.facade_battery import check_statement_views
from edgar_sec.tools.xbrl_eval.statement_view_summaries import (
    _equity_summary,
    _statement_summary,
    _topic_summary,
)
from edgar_sec.tools.xbrl_eval.statement_view_vocabulary import (
    FINANCIAL_VIEWS,
    SCALARS,
    SERIES,
    STATEMENT_FACTORIES,
    TOLERANCE,
    TOPIC_VIEWS,
    YOY,
)

if TYPE_CHECKING:
    from edgar_sec.apps.client.xbrl import Xbrl


def _guard(fn: Callable[[], Any]) -> tuple[Any, str | None]:
    """Run one surface call; an exception becomes report data."""
    try:
        return fn(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _surface(surface: Any, name: str) -> Any:
    """One attribute from a surface: properties return, methods build."""
    attr = getattr(surface, name)
    return attr() if callable(attr) else attr


def _in_filed(value: float, filed_values: Sequence[float]) -> bool:
    """Whether a served value appears among filed undimensioned numerics."""
    return any(abs(value - filed) <= TOLERANCE for filed in filed_values)


def _filing_cells(xbrl: Xbrl) -> dict[str, Any]:
    """Every driver cell for one loaded facade, raw outcomes only."""
    cells: dict[str, Any] = {}
    facts = xbrl.facts
    filed_values = [
        float(fact.value)
        for fact in facts
        if isinstance(fact.value, (int, float)) and not fact.dimensions
    ]
    dei_filed = sum(1 for fact in facts if fact.concept_qname.split(":", 1)[0] == "dei")
    for name in STATEMENT_FACTORIES:
        view, error = _guard(lambda n=name: _surface(xbrl.statements, n))
        cell: dict[str, Any] = {"kind": "statement", "error": error}
        if error is None:
            cell.update(_statement_summary(view))
        cells[f"statements.{name}"] = cell
    view, error = _guard(lambda: xbrl.statements.equity_rollforward())
    cell = {"kind": "view", "error": error}
    if error is None:
        cell.update(_equity_summary(view))
    cells["statements.equity_rollforward"] = cell
    cover, error = _guard(lambda: xbrl.statements.cover())
    cells["statements.cover"] = {
        "kind": "cover",
        "error": error,
        "facts": None if error is not None else len(cover),
        "dei_filed": dei_filed,
    }
    for name in TOPIC_VIEWS:
        view, error = _guard(lambda n=name: _surface(xbrl.statements, n))
        cell = {"kind": "view", "error": error}
        if error is None:
            cell.update(_topic_summary(name, view))
        cells[f"statements.{name}"] = cell
    catalog, error = _guard(lambda: check_statement_views(xbrl))
    cells["statements.catalog"] = {
        "kind": "catalog",
        "error": error,
        "role_count": None if error is not None else catalog["role_count"],
        "violations": [] if error is not None else catalog["violations"],
        "exceptions": [] if error is not None else catalog["exceptions"],
        "face_totals": [] if error is not None else catalog["face_totals"],
    }
    for name in SCALARS:
        value, error = _guard(lambda n=name: getattr(xbrl.financials, n))
        span, span_error = _guard(lambda n=name: xbrl.financials.span_class(n))
        cells[f"financials.{name}"] = {
            "kind": "scalar",
            "error": error,
            "value": value,
            "in_filed": (
                None if value is None else _in_filed(float(value), filed_values)
            ),
            "span_class": None if span_error is not None else span,
            "span_error": span_error,
        }
    fcf = cells["financials.free_cash_flow"]
    ocf = cells["financials.operating_cash_flow"]["value"]
    capex = cells["financials.capex"]["value"]
    fcf["derived_verified"] = (
        None
        if fcf["value"] is None or ocf is None or capex is None
        else abs(float(fcf["value"]) - (float(ocf) - float(capex))) <= TOLERANCE
    )
    for name in SERIES:
        series, error = _guard(lambda n=name: getattr(xbrl.financials, n))
        cell = {"kind": "series", "error": error, "points": 0}
        if error is None and series:
            latest = max(series)
            cell.update(
                {
                    "points": len(series),
                    "latest_period": latest,
                    "latest_value": series[latest],
                    "in_filed": _in_filed(float(series[latest]), filed_values),
                }
            )
        cells[f"financials.{name}"] = cell
    for name in YOY:
        yoy, error = _guard(lambda n=name: getattr(xbrl.financials, n))
        cells[f"financials.{name}"] = {
            "kind": "yoy",
            "error": error,
            "value": None if yoy is None else list(yoy),
        }
    for name in FINANCIAL_VIEWS:
        view, error = _guard(lambda n=name: _surface(xbrl.financials, n))
        cell = {"kind": "view", "error": error}
        if error is None:
            if name == "equity_rollforward":
                cell.update(_equity_summary(view))
            else:
                cell.update(_topic_summary(name, view))
        cells[f"financials.{name}"] = cell
    metrics, error = _guard(lambda: xbrl.financials.metrics())
    cells["financials.metrics"] = {
        "kind": "metrics",
        "error": error,
        "values": {} if error is not None else dict(metrics),
    }
    return cells
