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
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.corpus.corpus_index import _worker_taxonomy
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.discovery.cohort import load_seed_cohort
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.xbrl_review.bundles import bundle_dir_for
from edgar_sec.pipelines.xbrl_review.cohort import canonical_probe_cohort_path
from edgar_sec.tools.xbrl_eval.statement_view_cells import _filing_cells, _guard
from edgar_sec.tools.xbrl_eval.statement_view_census import _segment_census
from edgar_sec.tools.xbrl_eval.statement_view_classification import classify_record
from edgar_sec.tools.xbrl_eval.statement_view_vocabulary import BLOCKED
from edgar_sec.tools.xbrl_eval.xbrl_cross_form_census import analyze_facts


_WORKER_REGISTRY: Path | None = None


_WORKER_SEGMENT_CENSUS = False


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
        if _WORKER_SEGMENT_CENSUS:
            census, census_error = _guard(lambda: _segment_census(xbrl))
            record["segment_census"] = (
                {"error": census_error} if census_error is not None else census
            )
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
    segment_census: bool = False,
) -> dict[str, Any]:
    """Run the driver over one shard of the registry's filings."""
    global _WORKER_REGISTRY, _WORKER_SEGMENT_CENSUS
    _WORKER_REGISTRY = registry_path
    _WORKER_SEGMENT_CENSUS = segment_census
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
    parser.add_argument(
        "--segment-census",
        action="store_true",
        help="Also record each filing's per-(concept, axis) breakdown census.",
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
            segment_census=args.segment_census,
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
