from __future__ import annotations

from collections import Counter
from pathlib import Path

from edgar_sec.pipelines.document_inventory.review_artifacts.comparison import (
    compare_review_analysis_runs,
)
from edgar_sec.pipelines.document_inventory.review_artifacts.run_loading import (
    _load_run,
)


def analyze_review_runs(
    run_directories: list[Path],
    *,
    artifacts_root: Path | None = None,
    accessions: set[str] | None = None,
) -> dict:
    if not run_directories:
        raise ValueError("at least one review run is required")
    run_ids = [path.name for path in run_directories]
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("review run identifiers must be unique")

    runs = [_load_run(path, accessions, artifacts_root) for path in run_directories]
    comparisons = [compare_review_analysis_runs(runs[0], run) for run in runs[1:]]
    counts = Counter(
        finding["code"]
        for run in runs
        for case in run["cases"]
        for finding in case["findings"]
    )
    routes = Counter(
        finding["route"]
        for run in runs
        for case in run["cases"]
        for finding in case["findings"]
        if finding["code"] == "acquisition_route"
    )
    return {
        "schema_version": 1,
        "network_requests": 0,
        "baseline_run": runs[0]["run_id"],
        "runs": [
            {
                "run_id": run["run_id"],
                "case_count": len(run["cases"]),
                "parser_fingerprints": sorted(run["parser_fingerprints"]),
                "entry_count": sum(case["entry_count"] for case in run["cases"]),
                "filing_form_context_cases": sum(
                    len(case["filing_forms"]) == 1 for case in run["cases"]
                ),
                "findings": dict(sorted(run["finding_counts"].items())),
                "routes": dict(sorted(run["route_counts"].items())),
            }
            for run in runs
        ],
        "comparisons": comparisons,
        "finding_counts": dict(sorted(counts.items())),
        "acquisition_routes": dict(sorted(routes.items())),
        "findings": [
            finding
            for run in runs
            for case in run["cases"]
            for finding in case["findings"]
        ],
    }
