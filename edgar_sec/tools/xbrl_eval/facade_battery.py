"""Step 10 facade verification battery over the archived XBRL cohorts.

Loads full-fidelity fixture bundles, builds the client facade, and
records per-filing check outcomes as JSON for adjudication.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.catalog import CatalogEntry
from edgar_sec.apps.client.fiscal import duration_length_class
from edgar_sec.apps.client.presentation import PresentationView, period_key_class
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.storage.atomic import atomic_write_json

REPO = Path(__file__).resolve().parents[3]
XBRL_FIXTURES = REPO / "tests" / "fixtures" / "xbrl"
COHORT_NAMES = ("seed", "vintage", "sp100")
MODES = ("standard", "detailed", "summary")
TOLERANCE = 0.5

_FACE_CHECKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("IncomeStatement", ("revenue", "net_income")),
    ("BalanceSheet", ("total_assets",)),
    ("CashFlow", ("operating_cash_flow",)),
)
_STATEMENT_CALLS = (
    "income_statement",
    "balance_sheet",
    "cash_flow_statement",
    "comprehensive_income_statement",
    "equity_rollforward",
    "derivatives",
    "debt",
    "cash_rollforward",
    "fair_value_hierarchy",
    "cover",
)
_SCALARS = (
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
_SERIES = (
    "revenue_series",
    "revenue_yoy",
    "gross_profit_series",
    "gross_profit_yoy",
    "operating_income_series",
    "operating_income_yoy",
    "net_income_series",
    "net_income_yoy",
    "total_assets_series",
    "total_assets_yoy",
    "total_liabilities_series",
    "total_liabilities_yoy",
    "total_equity_series",
    "total_equity_yoy",
    "operating_cash_flow_series",
    "operating_cash_flow_yoy",
    "rpo_series",
    "rpo_yoy",
    "capex_series",
)
_FINANCIAL_VIEWS = (
    "derivatives",
    "debt",
    "cash_rollforward",
    "fair_value_hierarchy",
    "level3_rollforward",
    "pension_funded_status",
    "equity_rollforward",
    "segment_breakdown",
    "metrics",
)
_CROSS_SURFACE = (
    "equity_rollforward",
    "fair_value_hierarchy",
    "derivatives",
    "debt",
    "cash_rollforward",
)
_F5_FOLDERS = ("msft_2024_10k", "aapl_2024_10k")


def _guard(fn: Callable[[], Any]) -> tuple[Any, str | None]:
    """Run one check; an exception becomes report data, never a death."""
    try:
        return fn(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def cohort_folders(cohort: str, subset: Sequence[str] | None = None) -> list[str]:
    """Bundle folders of one cohort, in name order, optionally subset."""
    root = XBRL_FIXTURES / cohort
    folders = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "facts.parquet").exists()
    )
    if subset is not None:
        wanted = set(subset)
        folders = [folder for folder in folders if folder in wanted]
    return folders


def _face_value_check(
    view: PresentationView,
    expected: float,
    periods: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Whether the expected value appears as a face value at the served period.

    periods names the scalar's served-span face keys; the check anchors
    there when given, else at the latest annual period as before.
    """
    if not view.periods:
        return {"found": False, "period": None, "nearest": None}
    if periods:
        anchors = [key for key in periods if key in view.periods]
        if not anchors:
            return {"found": False, "period": periods[-1], "nearest": None}
    else:
        annual = [p for p in view.periods if period_key_class(p) is None]
        anchors = [annual[-1] if annual else view.periods[-1]]
    nearest: dict[str, Any] | None = None
    for period in anchors:
        for row in view.rows:
            if row.dimensions:
                continue
            value = row.values.get(period)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if abs(float(value) - expected) <= TOLERANCE:
                return {"found": True, "period": period, "nearest": None}
            gap = abs(float(value) - expected)
            if nearest is None or gap < nearest["difference"]:
                nearest = {
                    "concept": row.concept,
                    "value": float(value),
                    "difference": gap,
                }
    return {"found": False, "period": anchors[-1], "nearest": nearest}


def _fact_period_key(fact: XbrlFact, span: str) -> str | None:
    """A fact's presentation period key, when the fact is in the span class."""
    if span == "INSTANT":
        return fact.instant_date if fact.period_type == "instant" else None
    if fact.period_type != "duration" or not fact.start_date or not fact.end_date:
        return None
    if duration_length_class(fact.start_date, fact.end_date) != span:
        return None
    return fact.end_date if span == "ANNUAL" else f"{fact.end_date} ({span})"


def _served_period_keys(xbrl: Xbrl, metric: str, expected: float) -> tuple[str, ...]:
    """Face period keys of the span the metric's scalar was served from.

    Keys come from undimensioned facts carrying the served value in the
    served span class; empty when the span or a carrying fact is unknown.
    """
    span, error = _guard(lambda: xbrl.financials.span_class(metric))
    if error is not None or span is None:
        return ()
    keys = {
        key
        for fact in xbrl.facts
        if not fact.dimensions
        and isinstance(fact.value, (int, float))
        and not isinstance(fact.value, bool)
        and abs(float(fact.value) - expected) <= TOLERANCE
        and (key := _fact_period_key(fact, span)) is not None
    }
    return tuple(sorted(keys))


def _mode_violation(rows: dict[str, int]) -> bool:
    """Whether the three mode counts break summary <= standard <= detailed."""
    if len(rows) != len(MODES):
        return False
    return not (rows["summary"] <= rows["standard"] <= rows["detailed"])


def _catalog_entries(xbrl: Xbrl) -> tuple[CatalogEntry, ...]:
    """Catalog entries through the public list/get surface, in filed order."""
    entries = []
    for role in xbrl.statements.list_available()["role"].tolist():
        entry = xbrl.statements.get(role)
        if entry is not None:
            entries.append(entry)
    return tuple(entries)


def check_statement_views(xbrl: Xbrl) -> dict[str, Any]:
    """Statement-view battery for one facade: roles, modes, face totals."""
    entries = _catalog_entries(xbrl)
    roles: dict[str, Any] = {}
    violations: list[str] = []
    exceptions: list[dict[str, Any]] = []
    for entry in entries:
        rows: dict[str, int] = {}
        for mode in MODES:
            count, error = _guard(
                lambda uri=entry.role_uri, m=mode: len(
                    xbrl.statements.view(uri, mode=m).rows
                )
            )
            if error is not None:
                exceptions.append(
                    {
                        "check": "view",
                        "role": entry.role_uri,
                        "mode": mode,
                        "error": error,
                    }
                )
            else:
                rows[mode] = count
        violation = _mode_violation(rows)
        if violation:
            violations.append(entry.role_uri)
        roles[entry.role_uri] = {
            "title": entry.title,
            "category": entry.category,
            "family": entry.family,
            "rows": rows,
            "violation": violation,
        }
    return {
        "role_count": len(entries),
        "roles": roles,
        "violations": violations,
        "exceptions": exceptions,
        "face_totals": _face_total_checks(xbrl, entries),
    }


def _face_total_checks(
    xbrl: Xbrl, entries: tuple[CatalogEntry, ...]
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for family, metrics in _FACE_CHECKS:
        family_entries = [entry for entry in entries if entry.family == family]
        for metric in metrics:
            checks.append(_face_total_check(xbrl, family, family_entries, metric))
    return checks


def _face_total_check(
    xbrl: Xbrl, family: str, family_entries: list[CatalogEntry], metric: str
) -> dict[str, Any]:
    record: dict[str, Any] = {"family": family, "metric": metric}
    if not family_entries:
        return {**record, "status": "skipped", "reason": "family role absent"}
    expected, error = _guard(lambda: getattr(xbrl.financials, metric))
    if error is not None:
        return {**record, "status": "error", "error": error}
    if expected is None:
        return {**record, "status": "skipped", "reason": "scalar is None"}
    record["expected"] = float(expected)
    anchors = _served_period_keys(xbrl, metric, float(expected))
    nearest: dict[str, Any] | None = None
    period: str | None = None
    for entry in family_entries:
        view, view_error = _guard(
            lambda uri=entry.role_uri: xbrl.statements.view(uri, mode="standard")
        )
        if view_error is not None:
            return {**record, "status": "error", "error": view_error}
        outcome = _face_value_check(view, float(expected), anchors)
        if outcome["found"]:
            return {
                **record,
                "status": "found",
                "role": entry.role_uri,
                "period": outcome["period"],
            }
        period = outcome["period"]
        candidate = outcome["nearest"]
        if candidate is not None and (
            nearest is None or candidate["difference"] < nearest["difference"]
        ):
            nearest = {**candidate, "role": entry.role_uri}
    return {
        **record,
        "status": "missing",
        "period": period,
        "nearest": nearest,
    }


def _surface_view(surface: Any, name: str) -> Any:
    """One view from a surface: properties return views, methods build them."""
    attr = getattr(surface, name)
    return attr() if callable(attr) else attr


def _invoke_all(xbrl: Xbrl) -> dict[str, str]:
    """Invoke every wired view and served value; record ok or the exception."""
    outcomes: dict[str, str] = {}

    def record(name: str, fn: Callable[[], Any]) -> None:
        _, error = _guard(fn)
        outcomes[name] = "ok" if error is None else f"exception: {error}"

    for name in _STATEMENT_CALLS:
        record(f"statements.{name}", lambda n=name: _surface_view(xbrl.statements, n))
    for name in _SCALARS:
        record(f"financials.{name}", lambda n=name: getattr(xbrl.financials, n))
    for name in _SERIES:
        record(f"financials.{name}", lambda n=name: getattr(xbrl.financials, n))
    for name in _FINANCIAL_VIEWS:
        record(f"financials.{name}", lambda n=name: _surface_view(xbrl.financials, n))
    return outcomes


def _cross_surface(xbrl: Xbrl) -> dict[str, Any]:
    """Compare the five shared views' rendered ASCII across both surfaces."""
    outcomes: dict[str, Any] = {}
    for name in _CROSS_SURFACE:

        def compare(n: str = name) -> bool:
            left = _surface_view(xbrl.statements, n).render_ascii()
            right = _surface_view(xbrl.financials, n).render_ascii()
            return left == right

        match, error = _guard(compare)
        if error is not None:
            outcomes[name] = {"status": "exception", "error": error}
        else:
            outcomes[name] = {"status": "match" if match else "mismatch"}
    return outcomes


def _hierarchy_tallies(xbrl: Xbrl) -> dict[str, Any]:
    view, error = _guard(lambda: xbrl.statements.fair_value_hierarchy())
    if error is not None:
        return {"status": "exception", "error": error}
    rows = view.rows
    return {
        "status": "ok",
        "rows": len(rows),
        "verified": sum(1 for row in rows if row.verified is True),
        "discrepancy": sum(1 for row in rows if row.verified is False),
        "unverified": sum(1 for row in rows if row.verified is None),
        "l3_tied_true": sum(1 for row in rows if row.l3_tied is True),
        "l3_tied_false": sum(1 for row in rows if row.l3_tied is False),
        "l3_tied_none": sum(1 for row in rows if row.l3_tied is None),
    }


def _locate_check(xbrl: Xbrl) -> dict[str, Any]:
    result, error = _guard(lambda: xbrl.search("revenue"))
    if error is not None:
        return {"status": "exception", "error": error}
    if not result.hits:
        return {"status": "skipped", "reason": "no revenue search hits"}
    hit = result.hits[0]
    face_periods = [
        fact.instant_date or fact.end_date
        for fact in hit.facts
        if not fact.dimensions and (fact.instant_date or fact.end_date)
    ]
    period = max(face_periods) if face_periods else None
    location, loc_error = _guard(lambda: xbrl.locate(hit.qname, period=period))
    if loc_error is not None:
        return {"status": "exception", "error": loc_error, "qname": hit.qname}
    return {
        "status": "ok",
        "qname": hit.qname,
        "period": period,
        "placements": len(location.placements),
        "calculation_parents": len(location.calculation_parents),
        "fact_present": location.fact is not None,
    }


def check_seed_surfaces(xbrl: Xbrl) -> dict[str, Any]:
    """Seed-only surface consistency for one facade, peer search excluded."""
    query, query_error = _guard(lambda: xbrl.query("revenue"))
    return {
        "invocations": _invoke_all(xbrl),
        "cross_surface": _cross_surface(xbrl),
        "fair_value_hierarchy": _hierarchy_tallies(xbrl),
        "locate": _locate_check(xbrl),
        "query_revenue_status": (
            None if query_error is not None else str(query.status)
        ),
        "query_revenue_error": query_error,
        "peer_search": {"status": "not_run"},
    }


def check_peer_search(source_qname: str | None, peer: Xbrl) -> dict[str, Any]:
    """One filing's revenue qname searched in the next filing's facade."""
    if source_qname is None:
        return {"status": "skipped", "reason": "source filing has no revenue hit"}
    result, error = _guard(lambda: peer.search(source_qname))
    if error is not None:
        return {"status": "exception", "error": error, "term_qname": source_qname}
    if not result.hits:
        return {"status": "no_hits", "term_qname": source_qname}
    top = result.hits[0]
    return {
        "status": "ok",
        "term_qname": source_qname,
        "top_qname": top.qname,
        "top_tier": top.tier,
        "top_rule": top.rule,
        "hit_count": len(result.hits),
    }


_WORKER_TAXONOMY: DomainTaxonomy | None = None


def _worker_taxonomy() -> DomainTaxonomy:
    """This process's domain taxonomy, loaded lazily on first use."""
    global _WORKER_TAXONOMY
    if _WORKER_TAXONOMY is None:
        _WORKER_TAXONOMY = load_domain_taxonomy()
    return _WORKER_TAXONOMY


def _filing_work(item: tuple[str, str, str | None]) -> tuple[str, str, dict[str, Any]]:
    """One filing's full check pass; the pool work unit (top-level, picklable)."""
    cohort, folder, peer_folder = item
    started = time.perf_counter()
    record: dict[str, Any] = {}
    peer_seconds = 0.0
    xbrl, error = _guard(
        lambda: Xbrl.from_bundle(XBRL_FIXTURES / cohort / folder, _worker_taxonomy())
    )
    if error is not None:
        record["load_error"] = error
    else:
        record["accession"] = xbrl.accession
        record["fact_count"] = len(xbrl.facts)
        record["statement_views"] = check_statement_views(xbrl)
        if cohort == "seed":
            surfaces = check_seed_surfaces(xbrl)
            peer_started = time.perf_counter()
            peer_record: dict[str, Any] = {"peer": peer_folder}
            if peer_folder == folder:
                peer_record.update({"status": "skipped", "reason": "single filing"})
            else:
                peer, peer_error = _guard(
                    lambda target=peer_folder: Xbrl.from_bundle(
                        XBRL_FIXTURES / "seed" / str(target), _worker_taxonomy()
                    )
                )
                if peer_error is not None:
                    peer_record.update({"status": "exception", "error": peer_error})
                else:
                    peer_record.update(
                        check_peer_search(surfaces["locate"].get("qname"), peer)
                    )
            surfaces["peer_search"] = peer_record
            peer_seconds = time.perf_counter() - peer_started
            record["surfaces"] = surfaces
    record["seconds"] = round(time.perf_counter() - started - peer_seconds, 3)
    return cohort, folder, record


def _summarize_cohort(cohort: str, records: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "filings": len(records),
        "load_errors": sum(
            1 for r in records.values() if "load_error" in r or "worker_error" in r
        ),
        "roles": 0,
        "mode_violations": 0,
        "view_exceptions": 0,
        "face_totals": Counter(),
    }
    for record in records.values():
        views = record.get("statement_views")
        if views is None:
            continue
        summary["roles"] += views["role_count"]
        summary["mode_violations"] += len(views["violations"])
        summary["view_exceptions"] += len(views["exceptions"])
        for check in views["face_totals"]:
            summary["face_totals"][check["status"]] += 1
    summary["face_totals"] = dict(summary["face_totals"])
    if cohort == "seed":
        summary.update(_summarize_seed(records))
    return summary


def _summarize_seed(records: dict[str, Any]) -> dict[str, Any]:
    invocations = Counter()
    mismatches: list[dict[str, str]] = []
    hierarchy = Counter()
    peer = Counter()
    statuses = Counter()
    for folder, record in records.items():
        surfaces = record.get("surfaces")
        if surfaces is None:
            continue
        for outcome in surfaces["invocations"].values():
            invocations["ok" if outcome == "ok" else "exception"] += 1
        for name, outcome in surfaces["cross_surface"].items():
            if outcome["status"] != "match":
                mismatches.append(
                    {"filing": folder, "view": name, "status": outcome["status"]}
                )
        tallies = surfaces["fair_value_hierarchy"]
        if tallies.get("status") == "ok":
            for key in (
                "rows",
                "verified",
                "discrepancy",
                "unverified",
                "l3_tied_true",
                "l3_tied_false",
                "l3_tied_none",
            ):
                hierarchy[key] += tallies[key]
        else:
            hierarchy["exception"] += 1
        peer[surfaces.get("peer_search", {}).get("status", "not_run")] += 1
        if surfaces["query_revenue_status"] is not None:
            statuses[surfaces["query_revenue_status"]] += 1
    f5: dict[str, Any] = {}
    for folder in _F5_FOLDERS:
        record = records.get(folder)
        if record is not None and "surfaces" in record:
            f5[folder] = record["surfaces"]["query_revenue_status"]
    return {
        "surface_invocations": dict(invocations),
        "cross_surface_mismatches": mismatches,
        "fair_value_hierarchy_totals": dict(hierarchy),
        "peer_search": dict(peer),
        "query_revenue_statuses": dict(statuses),
        "f5_expected_ambiguous": f5,
        "f5_invariant_ok": (
            all(status == "AMBIGUOUS" for status in f5.values()) if f5 else None
        ),
    }


def _default_workers() -> int:
    """Default pool size: the repo resource seam (cores bounded by memory)."""
    return derive_resources().workers


def _crashed_record(exc: BaseException) -> dict[str, Any]:
    """A filing record for a worker that died before returning its own."""
    return {"worker_error": f"{type(exc).__name__}: {exc}", "seconds": 0.0}


def _collect_records(
    items: list[tuple[str, str, str | None]], workers: int
) -> dict[tuple[str, str], dict[str, Any]]:
    """Run the filing work items, sequentially or over a process pool."""
    collected: dict[tuple[str, str], dict[str, Any]] = {}
    if workers <= 1 or len(items) <= 1:
        for item in items:
            cohort, folder, record = _filing_work(item)
            collected[(cohort, folder)] = record
        return collected
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_filing_work, item): item for item in items}
        for future, (cohort, folder, _peer) in futures.items():
            try:
                _, _, record = future.result()
            except Exception as exc:
                record = _crashed_record(exc)
            collected[(cohort, folder)] = record
    return collected


def run_battery(
    cohorts: Sequence[str],
    subset: Sequence[str] | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Run the battery over the named cohorts and assemble the report."""
    items: list[tuple[str, str, str | None]] = []
    folders_by_cohort: dict[str, list[str]] = {}
    for cohort in cohorts:
        folders = cohort_folders(cohort, subset)
        folders_by_cohort[cohort] = folders
        for index, folder in enumerate(folders):
            peer = folders[(index + 1) % len(folders)] if cohort == "seed" else None
            items.append((cohort, folder, peer))
    collected = _collect_records(items, workers)
    report: dict[str, Any] = {"cohorts": {}}
    for cohort in cohorts:
        records = {
            folder: collected[(cohort, folder)] for folder in folders_by_cohort[cohort]
        }
        report["cohorts"][cohort] = {
            "filings": records,
            "summary": _summarize_cohort(cohort, records),
        }
    return report


def _print_summary(report: dict[str, Any]) -> None:
    for cohort, data in report["cohorts"].items():
        summary = data["summary"]
        sys.stdout.write(
            f"[{cohort}] filings={summary['filings']} "
            f"load_errors={summary['load_errors']} roles={summary['roles']} "
            f"mode_violations={summary['mode_violations']} "
            f"view_exceptions={summary['view_exceptions']} "
            f"face_totals={summary['face_totals']}\n"
        )
        if cohort == "seed":
            sys.stdout.write(
                f"  invocations={summary['surface_invocations']} "
                f"cross_surface_mismatches="
                f"{len(summary['cross_surface_mismatches'])} "
                f"peer_search={summary['peer_search']} "
                f"f5_invariant_ok={summary['f5_invariant_ok']}\n"
            )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Step 10 facade verification battery over cohorts.",
    )
    parser.add_argument(
        "--cohorts",
        nargs="+",
        choices=COHORT_NAMES,
        default=["seed"],
        help="Cohorts to run (default: seed).",
    )
    parser.add_argument(
        "--folders",
        nargs="*",
        default=None,
        help="Optional subset of bundle folders, applied to every cohort.",
    )
    parser.add_argument("--out", type=Path, required=True, help="Report JSON path.")
    parser.add_argument(
        "--workers",
        type=int,
        default=_default_workers(),
        help="Filings processed concurrently (default: derive_resources().workers; 1 = sequential).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: run the battery, write the JSON report, print a summary."""
    args = _build_parser().parse_args(argv)
    for cohort in args.cohorts:
        if not (XBRL_FIXTURES / cohort).is_dir():
            sys.stderr.write(f"cohort fixtures not found: {cohort}\n")
            return 2
    try:
        report = run_battery(args.cohorts, args.folders, workers=args.workers)
        atomic_write_json(args.out, report, indent=2)
    except Exception as exc:
        sys.stderr.write(f"facade battery failed: {type(exc).__name__}: {exc}\n")
        return 2
    _print_summary(report)
    sys.stdout.write(f"Report written to: {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
