"""Interactive operator console for XBRL semantic review and DAG staging."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    PickItem,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_paginated_choice,
)
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.review.diff import compare_review_runs
from edgar_sec.pipelines.xbrl_review.cli import main as cli_main
from edgar_sec.pipelines.xbrl_review.discovery import (
    discover_cohorts,
    discover_review_runs,
)
from edgar_sec.pipelines.xbrl_review.paths import (
    HYPOTHESES_FILE,
    xbrl_paths,
)
from edgar_sec.pipelines.xbrl_review.review import (
    execute_review_generation,
    promote_review_rule,
)
from edgar_sec.pipelines.xbrl_review.review_artifacts.adapter import XbrlReviewAdapter

MENU_TITLE = "XBRL Semantic Review & Staging"


def _action_project() -> None:
    cli_args = ["project"]
    cohorts = discover_cohorts()
    if not cohorts:
        print("No dataset cohorts discovered.")
        return
    cohort_items = [
        PickItem(key=str(idx), label=c["label"], value=str(c["path"]))
        for idx, c in enumerate(cohorts, start=1)
    ]
    chosen_cohort = prompt_paginated_choice(
        cohort_items, prompt_label="Select cohort dataset"
    )
    if chosen_cohort is None:
        return
    cli_args.extend(["--dataset", chosen_cohort.value])

    print(f"\nProjecting XBRL execution with: {' '.join(cli_args)}")
    cli_main(cli_args)


def _action_generate_review() -> None:
    cohorts = discover_cohorts()
    if not cohorts:
        print("No cohorts discovered.")
        return
    items = [
        PickItem(key=str(idx), label=c["label"], value=c["path"])
        for idx, c in enumerate(cohorts, start=1)
    ]
    chosen = prompt_paginated_choice(
        items, prompt_label="Select cohort for review run", default=items[0]
    )
    if chosen is None:
        return

    limit_items = [
        PickItem(key="1", label="All filings in cohort", value=None),
        PickItem(key="2", label="10 filings (quick verification)", value=10),
        PickItem(key="3", label="25 filings", value=25),
        PickItem(key="4", label="50 filings", value=50),
    ]
    chosen_limit = prompt_paginated_choice(
        limit_items, prompt_label="Select filing limit", default=limit_items[0]
    )
    limit = chosen_limit.value if chosen_limit is not None else None

    raw = json.loads(chosen.value.read_text(encoding="utf-8"))
    filings = raw if isinstance(raw, list) else raw.get("filings", [])
    if limit is not None:
        filings = filings[:limit]

    print(f"\nGenerating review artifacts for {len(filings)} filing(s)...")
    run = execute_review_generation(filings)
    print(
        f"Review run created: {run.run_id}\n"
        f"  Total filings:   {run.total_filings}\n"
        f"  Solved nodes:    {run.solved_count}\n"
        f"  Quarantined:     {run.quarantine_count}\n"
        f"  Hypotheses:      {run.hypotheses_count}\n"
        f"  Output path:     {run.run_dir}"
    )


def _action_compare_runs() -> None:
    runs = discover_review_runs()
    if len(runs) < 2:
        print("Need at least 2 historical review runs to perform comparison.")
        return
    items = [
        PickItem(
            key=str(idx),
            label=f"{r['run_id']} ({r['total_filings']} filings, {r['total_hypotheses']} hyp)",
            value=r["path"],
        )
        for idx, r in enumerate(runs, start=1)
    ]
    base_choice = prompt_paginated_choice(
        items, prompt_label="Select base review run", default=items[1]
    )
    if base_choice is None:
        return
    new_choice = prompt_paginated_choice(
        items, prompt_label="Select new review run", default=items[0]
    )
    if new_choice is None:
        return

    adapter = XbrlReviewAdapter()
    diff_dir = (
        xbrl_paths().review_runs_root
        / f"diff-{base_choice.value.name}_vs_{new_choice.value.name}"
    )
    print(f"\nComparing {base_choice.value.name} vs {new_choice.value.name}...")
    summary = compare_review_runs(
        base_dir=base_choice.value,
        new_dir=new_choice.value,
        output_dir=diff_dir,
        adapter=adapter,
    )
    print(
        f"\nComparison Summary:\n"
        f"  Total cases:  {summary.total_cases}\n"
        f"  Unchanged:    {summary.unchanged_count}\n"
        f"  Changed:      {summary.changed_count}\n"
        f"  Added:        {summary.added_count}\n"
        f"  Removed:      {summary.removed_count}\n"
        f"  Diff report:  {diff_dir / 'summary.txt'}"
    )


def _action_promote_rule() -> None:
    runs = discover_review_runs()
    if not runs:
        print("No review runs found.")
        return
    items = [
        PickItem(
            key=str(idx),
            label=f"{r['run_id']} ({r['total_hypotheses']} candidate hypotheses)",
            value=r["path"],
        )
        for idx, r in enumerate(runs, start=1)
    ]
    chosen_run = prompt_paginated_choice(
        items, prompt_label="Select review run to inspect", default=items[0]
    )
    if chosen_run is None:
        return

    cases_dir = chosen_run.value / "cases"
    all_hyps: list[dict] = []
    if cases_dir.is_dir():
        for cp in cases_dir.iterdir():
            hyp_p = cp / HYPOTHESES_FILE
            if hyp_p.is_file():
                try:
                    all_hyps.extend(pq.read_table(hyp_p).to_pylist())
                except (OSError, ValueError):
                    pass

    if not all_hyps:
        print(f"No candidate hypotheses found in {chosen_run.value.name}.")
        return

    hyp_items = [
        PickItem(
            key=str(idx),
            label=f"{h['rule_id']}: {h['source_concept']} -> {h['target_concept']} ({h.get('firm', '*')})",
            value=h,
        )
        for idx, h in enumerate(all_hyps, start=1)
    ]
    chosen_hyp = prompt_paginated_choice(
        hyp_items, prompt_label="Select hypothesis to promote"
    )
    if chosen_hyp is None:
        return

    evidence_path = chosen_run.value / "gate_evidence.json"
    if not evidence_path.is_file():
        print(
            "Promotion requires gate evidence: no gate_evidence.json in "
            f"{chosen_run.value}. Produce it with `review gates` and place "
            "it in the run directory."
        )
        return
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    rec = promote_review_rule(
        chosen_hyp.value["rule_id"], chosen_run.value, evidence=evidence
    )
    print(f"\nSuccessfully promoted rule: {rec.rule_id} -> {rec.target_concept}")


def _action_inspect_rules() -> None:
    db_p = xbrl_paths().unification_rules_db_path
    if not db_p.is_file():
        print(f"No unification rules database found at {db_p}")
        return
    con = connect(database=db_p)
    rows = con.execute(
        "SELECT rule_id, target_concept, source_concept, algebraic_weight, scope_firm FROM xbrl_unification_rules"
    ).fetchall()
    con.close()
    if not rows:
        print("Unification rules table is currently empty.")
        return
    print(f"\nPromoted Unification Rules ({len(rows)} rules):")
    for r in rows:
        print(f"  * {r[0]:<36} {r[2]} -> {r[1]} (weight={r[3]}, firm={r[4]})")


def _action_dag() -> None:
    dag_items = [
        PickItem(key="1", label="Status & HEAD Pointer", value=["dag", "status"]),
        PickItem(key="2", label="Commit Lineage Log", value=["dag", "log"]),
        PickItem(key="3", label="List Branches", value=["dag", "branch"]),
        PickItem(key="4", label="Integrity & Health Doctor", value=["dag", "doctor"]),
    ]
    chosen = prompt_paginated_choice(dag_items, prompt_label="Select DAG operation")
    if chosen is None:
        return
    cli_main(chosen.value)


def build_operator_menu() -> tuple[MenuAction, ...]:
    """Build the menu action loop for the XBRL review operator console."""
    return build_menu(
        menu_action("Project batch execution from plan or dataset", _action_project),
        menu_action("Generate review run from cohort", _action_generate_review),
        menu_action("Compare two review runs and report diffs", _action_compare_runs),
        menu_action("Inspect and promote candidate hypotheses", _action_promote_rule),
        menu_action("Query promoted unification rules database", _action_inspect_rules),
        menu_action("Inspect DAG catalog, lineage, and branch pointers", _action_dag),
    )


def main(argv: list[str] | None = None) -> int:
    """Operator console entrypoint delegating to interactive loop or CLI."""
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
