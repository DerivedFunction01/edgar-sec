"""Statement-view driver over the probe cohort's per-form samples.

Runs every XbrlStatements factory and XbrlFinancials metric per filing,
records raw outcomes plus filed-fact spot checks as JSON, and classifies
each cell served-faithful, served-honest, or blocked with its mechanism.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.discovery.cohort import (
    canonical_probe_cohort_path,
    load_seed_cohort,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.xbrl_review.bundles import bundle_dir_for
from edgar_sec.tools.xbrl_eval.facade_battery import check_statement_views
from edgar_sec.tools.xbrl_eval.xbrl_cross_form_census import analyze_facts

TOLERANCE = 0.5

STATEMENT_FACTORIES = (
    "income_statement",
    "balance_sheet",
    "cash_flow_statement",
    "comprehensive_income_statement",
    "plan_net_assets",
    "plan_changes",
    "fund_assets_liabilities",
    "fund_operations",
)
SCALARS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "operating_cash_flow",
    "rpo",
    "capex",
    "free_cash_flow",
    "uncommenced_leases",
)
SERIES = (
    "revenue_series",
    "gross_profit_series",
    "operating_income_series",
    "net_income_series",
    "total_assets_series",
    "total_liabilities_series",
    "total_equity_series",
    "operating_cash_flow_series",
    "rpo_series",
    "capex_series",
)
YOY = (
    "revenue_yoy",
    "gross_profit_yoy",
    "operating_income_yoy",
    "net_income_yoy",
    "total_assets_yoy",
    "total_liabilities_yoy",
    "total_equity_yoy",
    "operating_cash_flow_yoy",
    "rpo_yoy",
)
TOPIC_VIEWS = (
    "derivatives",
    "debt",
    "cash_rollforward",
    "fair_value_hierarchy",
)
FINANCIAL_VIEWS = TOPIC_VIEWS + (
    "level3_rollforward",
    "pension_funded_status",
    "segment_breakdown",
)

FAITHFUL = "served-faithful"
HONEST = "served-honest"
BLOCKED = "blocked"

MECH_ROOT = "missing root atom"
MECH_LABEL = "taxonomy-shaped label gap"
MECH_FISCAL = "fiscal-class refusal"
MECH_ACQUISITION = "acquisition posture"
MECH_PARSE = "parse posture"
MECH_UNVERIFIED = "served value not in filed facts"
MECH_EXCEPTION = "surface exception"
MECH_FACE = "face total absent from statement face"
MECH_MODE = "mode-order violation"


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


def _statement_summary(view: Any) -> dict[str, Any]:
    """Graph-shape summary of one composed statement view."""
    graph = view.graph
    valued = sum(1 for node in graph.nodes.values() if node.value is not None)
    return {
        "status": str(view.status),
        "message": view.message,
        "root": graph.root_qname or None,
        "nodes": len(graph.nodes),
        "valued_nodes": valued,
        "years": list(view.years),
    }


def _equity_summary(view: Any) -> dict[str, Any]:
    """Opening/closing/component summary of the equity rollforward."""
    return {
        "opening": view.opening,
        "closing": view.closing,
        "components": len(view.components),
        "antichain_members": len(view.antichain_members),
        "populated": view.closing is not None or len(view.components) > 0,
    }


def _topic_summary(name: str, view: Any) -> dict[str, Any]:
    """Disclosure-view summary; populated names content over absence."""
    if name == "derivatives":
        return {
            "notional_amount": view.notional_amount,
            "gross_assets": view.gross_assets,
            "net_assets": view.net_assets,
            "positions": len(view.positions),
            "risk_categories": len(view.risk_categories),
            "populated": view.notional_amount is not None or len(view.positions) > 0,
        }
    if name == "debt":
        return {
            "total_debt": view.total_debt,
            "current_debt": view.current_debt,
            "long_term_debt": view.long_term_debt,
            "maturities": len(view.maturities),
            "populated": view.total_debt is not None or len(view.maturities) > 0,
        }
    if name == "cash_rollforward":
        return {
            "beginning": view.beginning,
            "net_change": view.net_change,
            "end": view.end,
            "rollforward_verified": view.rollforward_verified,
            "populated": view.end is not None or view.beginning is not None,
        }
    if name == "fair_value_hierarchy":
        rows = view.rows
        return {
            "rows": len(rows),
            "verified": sum(1 for row in rows if row.verified is True),
            "discrepancy": sum(1 for row in rows if row.verified is False),
            "unverified": sum(1 for row in rows if row.verified is None),
            "populated": len(rows) > 0,
        }
    if name == "level3_rollforward":
        return {
            "opening": view.opening,
            "closing": view.closing,
            "populated": view.closing is not None or view.opening is not None,
        }
    if name == "pension_funded_status":
        return {
            "assets_closing": view.assets_closing,
            "obligation_closing": view.obligation_closing,
            "assets_verified": view.assets_verified,
            "obligation_verified": view.obligation_verified,
            "populated": (
                view.assets_closing is not None or view.obligation_closing is not None
            ),
        }
    if name == "segment_breakdown":
        return {
            "concept": view.concept_qname,
            "axis": view.axis_qname,
            "total": view.total,
            "members": len(view.members),
            "verified": view.verified,
            "populated": view.total is not None or len(view.members) > 0,
        }
    raise ValueError(f"no topic summary for {name!r}")


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


def _exception_mechanism(error: str) -> str:
    """Name the mechanism an exception text evidences, conservatively."""
    lowered = error.lower()
    if "fiscal" in lowered or "length class" in lowered or "span" in lowered:
        return MECH_FISCAL
    if "no presentation role" in lowered or "no catalog" in lowered:
        return MECH_LABEL
    return MECH_EXCEPTION


def _classify_cell(cell: dict[str, Any], statement: bool) -> dict[str, str | None]:
    """One cell's classification and, when blocked, its mechanism."""
    kind = cell["kind"]
    error = cell.get("error")
    if kind == "catalog":
        return _classify_catalog(cell)
    if error is not None:
        return {"classification": BLOCKED, "mechanism": _exception_mechanism(error)}
    if kind == "statement":
        if cell["valued_nodes"] == 0:
            if cell.get("status") == "UNAVAILABLE":
                return {"classification": HONEST, "mechanism": None}
            if statement:
                return {"classification": BLOCKED, "mechanism": MECH_ROOT}
            return {"classification": HONEST, "mechanism": None}
        return {"classification": FAITHFUL, "mechanism": None}
    if kind == "cover":
        if cell["dei_filed"] == 0 and cell["facts"] == 0:
            return {"classification": HONEST, "mechanism": None}
        if cell["facts"] == cell["dei_filed"]:
            return {"classification": FAITHFUL, "mechanism": None}
        return {"classification": BLOCKED, "mechanism": MECH_PARSE}
    if kind == "scalar":
        if cell["value"] is None:
            return {"classification": HONEST, "mechanism": None}
        if cell.get("derived_verified") is not None:
            if cell["derived_verified"]:
                return {"classification": FAITHFUL, "mechanism": None}
            return {"classification": BLOCKED, "mechanism": MECH_UNVERIFIED}
        if cell["in_filed"]:
            return {"classification": FAITHFUL, "mechanism": None}
        return {"classification": BLOCKED, "mechanism": MECH_UNVERIFIED}
    if kind == "series":
        if cell["points"] == 0:
            return {"classification": HONEST, "mechanism": None}
        if cell.get("in_filed"):
            return {"classification": FAITHFUL, "mechanism": None}
        return {"classification": BLOCKED, "mechanism": MECH_UNVERIFIED}
    if kind == "yoy":
        outcome = HONEST if cell["value"] is None else FAITHFUL
        return {"classification": outcome, "mechanism": None}
    if kind == "view":
        outcome = FAITHFUL if cell.get("populated") else HONEST
        return {"classification": outcome, "mechanism": None}
    if kind == "metrics":
        outcome = FAITHFUL if cell["values"] else HONEST
        return {"classification": outcome, "mechanism": None}
    raise ValueError(f"unclassified cell kind {kind!r}")


def _classify_catalog(cell: dict[str, Any]) -> dict[str, str | None]:
    """Catalog cell: the worst of role exceptions, violations, face checks."""
    if cell.get("error") is not None:
        return {
            "classification": BLOCKED,
            "mechanism": _exception_mechanism(cell["error"]),
        }
    if cell["exceptions"]:
        return {"classification": BLOCKED, "mechanism": MECH_EXCEPTION}
    if cell["violations"]:
        return {"classification": BLOCKED, "mechanism": MECH_MODE}
    face = cell["face_totals"]
    if any(check["status"] in ("missing", "error") for check in face):
        return {"classification": BLOCKED, "mechanism": MECH_FACE}
    if face and all(check["status"] == "skipped" for check in face):
        return {"classification": HONEST, "mechanism": None}
    return {"classification": FAITHFUL, "mechanism": None}


def classify_record(record: dict[str, Any]) -> dict[str, Any]:
    """Classify every cell of one filing record against its posture."""
    statement = bool(record["analysis"]["statement"])
    verdicts = {
        name: _classify_cell(cell, statement) for name, cell in record["cells"].items()
    }
    return verdicts


_WORKER_TAXONOMY: DomainTaxonomy | None = None
_WORKER_REGISTRY: Path | None = None


def _worker_taxonomy() -> DomainTaxonomy:
    """This process's domain taxonomy, loaded lazily on first use."""
    global _WORKER_TAXONOMY
    if _WORKER_TAXONOMY is None:
        _WORKER_TAXONOMY = load_domain_taxonomy()
    return _WORKER_TAXONOMY


def _filing_work(item: tuple[str, str]) -> tuple[str, dict[str, Any]]:
    """One filing's driver pass; the pool work unit (top-level)."""
    folder, accession = item
    started = time.perf_counter()
    record: dict[str, Any] = {"folder": folder, "accession": accession}
    assert _WORKER_REGISTRY is not None
    xbrl, error = _guard(
        lambda: Xbrl.from_bundle(
            bundle_dir_for(accession, _WORKER_REGISTRY), _worker_taxonomy()
        )
    )
    if error is not None:
        record["load_error"] = error
    else:
        record["fact_count"] = len(xbrl.facts)
        record["analysis"] = analyze_facts(xbrl.facts)
        record["cells"] = _filing_cells(xbrl)
        record["classification"] = classify_record(record)
    record["seconds"] = round(time.perf_counter() - started, 3)
    return folder, record


def shard_filings(filings: Sequence[Any], shard: int, of: int) -> list[Any]:
    """Shard k of n over the accession-ordered filings: disjoint, complete."""
    if of < 1 or not 0 <= shard < of:
        raise ValueError(f"shard {shard} of {of} is out of range")
    ordered = sorted(filings, key=lambda f: str(f.accession))
    return [filing for index, filing in enumerate(ordered) if index % of == shard]


def run_driver(
    registry_path: Path,
    *,
    folders: Sequence[str] | None = None,
    shard: int = 0,
    of: int = 1,
    workers: int = 1,
) -> dict[str, Any]:
    """Run the driver over one shard of the registry's filings."""
    global _WORKER_REGISTRY
    _WORKER_REGISTRY = registry_path
    seeds = load_seed_cohort(registry_path)
    by_accession = {str(seed.accession): seed for seed in seeds}
    selected = shard_filings(seeds, shard, of)
    if folders is not None:
        wanted = set(folders)
        selected = [
            seed
            for seed in selected
            if bundle_dir_for(str(seed.accession), registry_path).name in wanted
        ]
    items = [
        (bundle_dir_for(str(seed.accession), registry_path).name, str(seed.accession))
        for seed in selected
    ]
    records: dict[str, dict[str, Any]] = {}
    if workers <= 1 or len(items) <= 1:
        for item in items:
            folder, record = _filing_work(item)
            records[folder] = record
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_filing_work, item): item for item in items}
            for future, (folder, accession) in futures.items():
                try:
                    _, record = future.result()
                except Exception as exc:
                    record = {
                        "folder": folder,
                        "accession": accession,
                        "load_error": f"{type(exc).__name__}: {exc}",
                        "seconds": 0.0,
                    }
                records[folder] = record
    for folder, record in records.items():
        seed = by_accession[record["accession"]]
        record.update(
            {
                "firm": seed.firm,
                "company_name": seed.company_name,
                "cik": str(seed.cik),
                "sic_code": seed.sic_code,
                "sector": seed.sector,
                "fy": seed.fy,
                "form": seed.form,
            }
        )
    return {
        "registry": str(registry_path),
        "shard": shard,
        "of": of,
        "filings": records,
    }


def merge_reports(reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Merge shard reports into one: filings disjoint, config consistent."""
    merged: dict[str, dict[str, Any]] = {}
    registry: str | None = None
    for report in reports:
        if registry is None:
            registry = report["registry"]
        elif report["registry"] != registry:
            raise ValueError("shard reports name different registries")
        for folder, record in report["filings"].items():
            if folder in merged:
                raise ValueError(f"filing {folder} appears in two shard reports")
            merged[folder] = record
    return {"registry": registry, "filings": merged}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the statement-view driver over probe-cohort filings.",
    )
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--folders", nargs="*", default=None)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--of", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--workers",
        type=int,
        default=derive_resources().workers,
        help="Filings processed concurrently (default: derive_resources().workers).",
    )
    parser.add_argument(
        "--merge",
        nargs="+",
        type=Path,
        default=None,
        help="Merge these shard reports into --out instead of running.",
    )
    parser.add_argument(
        "--score",
        action="store_true",
        help="Score the report against the pinned statement-view expectations.",
    )
    return parser


def _score_report(report: dict[str, Any]) -> int:
    """Print the statement-view gate verdict for one report; 0 = pass."""
    from edgar_sec.engine.xbrl.review.statement_views import score_statement_views

    score = score_statement_views(report)
    if score.passed:
        sys.stdout.write("Statement-view gate: PASS\n")
        return 0
    sys.stdout.write("Statement-view gate: FAIL\n")
    for failure in score.failures:
        sys.stdout.write(f"  {failure}\n")
    return 1


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: run one shard, or merge shard reports."""
    args = _build_parser().parse_args(argv)
    if args.merge is not None:
        reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.merge]
        merged = merge_reports(reports)
        atomic_write_json(args.out, merged, indent=2)
        sys.stdout.write(f"Merged report written to: {args.out}\n")
        return _score_report(merged) if args.score else 0
    registry = args.registry or canonical_probe_cohort_path()
    try:
        report = run_driver(
            registry,
            folders=args.folders,
            shard=args.shard,
            of=args.of,
            workers=args.workers,
        )
    except Exception as exc:
        sys.stderr.write(f"statement-view driver failed: {type(exc).__name__}: {exc}\n")
        return 2
    atomic_write_json(args.out, report, indent=2)
    blocked = sum(
        1
        for record in report["filings"].values()
        for verdict in record.get("classification", {}).values()
        if verdict["classification"] == BLOCKED
    )
    sys.stdout.write(
        f"filings={len(report['filings'])} blocked_cells={blocked}\n"
        f"Report written to: {args.out}\n"
    )
    return _score_report(report) if args.score else 0


if __name__ == "__main__":
    sys.exit(main())
