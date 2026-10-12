from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.review_artifacts.analyzer import (
    analyze_review_runs,
)


def cmd_review_analyze(args) -> int:
    artifacts_root = (
        Path(args.artifacts_root)
        if args.artifacts_root
        else resolve_paths().artifacts_root
    )
    paths = InventoryPaths(artifacts_root)
    run_directories = [paths.review_paths(run_id).root for run_id in args.run_ids]
    report = analyze_review_runs(
        run_directories,
        artifacts_root=artifacts_root,
        accessions=(
            {str(AccessionNumber.from_any(value)) for value in args.accessions}
            if args.accessions
            else None
        ),
    )

    if args.output:
        output = Path(args.output).expanduser().resolve()
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError(
                f"analysis output must be a new or empty directory: {output}"
            )
        output.mkdir(parents=True, exist_ok=True)
        atomic_write_json(output / "analysis.json", report)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Analyzed {len(report['runs'])} review run(s).")
        for run in report["runs"]:
            print(
                f"{run['run_id']}: {run['case_count']} cases, "
                f"{run['entry_count']} entries, "
                f"{run['filing_form_context_cases']} with filing-form context, "
                f"routes {run['routes']}, "
                f"{sum(run['findings'].values())} findings"
            )
        print("Findings by category:")
        for code, count in report["finding_counts"].items():
            print(f"  {code}: {count}")
        for comparison in report["comparisons"]:
            print(
                f"Compared {comparison['base_run']} -> {comparison['new_run']}: "
                f"{comparison['shared_input_count']} shared inputs, "
                f"{comparison['row_change_count']} row changes, "
                f"{comparison['observation_change_count']} observation changes, "
                f"{len(comparison['input_changed_accessions'])} input-changed accessions"
            )
        if args.output:
            print(f"Analysis written to: {output / 'analysis.json'}")
    return 0
