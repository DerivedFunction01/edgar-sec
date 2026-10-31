"""Command-line entrypoint for XBRL review pipeline operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from edgar_sec.foundation.runtime.settings.validators import positive_int_type
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.dag.cli import (
    attach_dag_subparser,
    dispatch_dag_subcommand,
)
from edgar_sec.infra.storage.review.cli import attach_review_artifact_subparsers
from edgar_sec.pipelines.xbrl_review.commands.project import (
    cmd_project,
    resolve_artifacts_root,
)
from edgar_sec.pipelines.xbrl_review.execution import execute_projection_run
from edgar_sec.pipelines.xbrl_review.gates import compute_gate_evidence
from edgar_sec.pipelines.xbrl_review.paths import xbrl_paths
from edgar_sec.pipelines.xbrl_review.review import promote_review_rule
from edgar_sec.pipelines.xbrl_review.review_artifacts.adapter import XbrlReviewAdapter
from edgar_sec.pipelines.xbrl_review.snapshot.specs import XBRL_RELATIONS


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifacts",
        dest="artifacts_root",
        default="",
        help="artifacts root override",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON to stdout")


def _cmd_promote(args: argparse.Namespace) -> int:
    """Execute rule promotion into the canonical knowledge base."""
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    rec = promote_review_rule(
        args.rule_id,
        args.run_dir,
        db_path=args.db_path,
        evidence=evidence,
    )
    print(f"Promoted rule: {rec.rule_id} -> {rec.target_concept}")
    return 0


def _cmd_gates(args: argparse.Namespace) -> int:
    """Compute gate evidence and write it to the output path."""
    census_summary = None
    if getattr(args, "census_summary", None):
        census_summary = json.loads(
            Path(args.census_summary).read_text(encoding="utf-8")
        )
    evidence = compute_gate_evidence(census_summary)
    atomic_write_json(args.output, evidence, indent=2)
    census = evidence.get("census", {})
    pair_gate = evidence.get("pair_gate", {})
    battery = evidence.get("battery", {})
    print(
        f"Gate evidence written to {args.output}: "
        f"census passed={census.get('passed')}, "
        f"pair_gate passed={pair_gate.get('passed')}/{pair_gate.get('total')}, "
        f"battery passed={battery.get('passed')}/{battery.get('total')}"
    )
    return 0


def _cmd_execute(args: argparse.Namespace) -> int:
    """Execute a projected run and publish its snapshot."""
    result = execute_projection_run(args.run_id, artifacts_root=args.artifacts_root)
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "snapshot_id": result.snapshot_id,
                    "chunks": result.chunks,
                    "filings": result.filings,
                    "solved_count": result.solved_count,
                    "quarantine_count": result.quarantine_count,
                    "hypotheses_count": result.hypotheses_count,
                    "wall_ms": result.wall_ms,
                },
                sort_keys=True,
            )
        )
    else:
        print(
            f"Executed run {result.run_id}: snapshot {result.snapshot_id}, "
            f"{result.chunks} chunks, {result.filings} filings, "
            f"{result.solved_count} solved, "
            f"{result.quarantine_count} quarantined, "
            f"{result.hypotheses_count} hypotheses, {result.wall_ms} ms"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for XBRL review pipeline commands."""
    parser = argparse.ArgumentParser(
        prog="xbrl",
        description="XBRL Semantic Lattice Projection, Review, and Snapshot DAG CLI",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # 1. Project command
    proj_p = sub.add_parser("project", help="project a dataset into a resumable run")
    proj_p.add_argument(
        "--dataset",
        dest="dataset",
        required=True,
        help="path to uniform Parquet or JSON dataset",
    )
    proj_p.add_argument("--queries", help="path to declarative queries file")
    proj_p.add_argument(
        "--base-snapshot-id", default=None, help="base snapshot ID override"
    )
    proj_p.add_argument(
        "--branch",
        default="main",
        help="DAG branch whose current tip is pinned as base (default: main)",
    )
    proj_p.add_argument(
        "--explicit-refresh",
        action="store_true",
        help="force re-solving of accessions",
    )
    proj_p.add_argument(
        "--chunk-size",
        type=positive_int_type,
        help="accessions per chunk (default: runtime.chunk_size)",
    )
    _add_output_options(proj_p)
    proj_p.set_defaults(func=cmd_project)

    # 2. Execute command
    exec_p = sub.add_parser("execute", help="execute a projected run")
    exec_p.add_argument("--run-id", required=True, help="projected run ID")
    _add_output_options(exec_p)
    exec_p.set_defaults(func=_cmd_execute)

    # 3. Review commands
    adapter = XbrlReviewAdapter()
    rev_commands = attach_review_artifact_subparsers(sub, adapter)

    prom_p = rev_commands.add_parser("promote", help="promote candidate rule to KB")
    prom_p.add_argument("--rule-id", required=True, help="hypothesis rule ID")
    prom_p.add_argument(
        "--run-dir", type=Path, required=True, help="review run directory"
    )
    prom_p.add_argument("--db-path", type=Path, help="target DuckDB database path")
    prom_p.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="path to gate-evidence JSON",
    )
    prom_p.set_defaults(func=_cmd_promote)

    gates_p = rev_commands.add_parser(
        "gates", help="compute gate evidence for promotion"
    )
    gates_p.add_argument(
        "--output", type=Path, required=True, help="gate-evidence JSON output path"
    )
    gates_p.add_argument(
        "--census-summary",
        type=Path,
        help="path to census summary JSON",
    )
    gates_p.set_defaults(func=_cmd_gates)

    # 4. Snapshot DAG commands
    dag_parser = attach_dag_subparser(
        sub,
        subcommand_name="dag",
        default_root=lambda: xbrl_paths(resolve_artifacts_root(None)).snapshots_root,
        default_specs=XBRL_RELATIONS,
    )
    dag_parser.set_defaults(
        func=lambda args: dispatch_dag_subcommand(
            args,
            default_root=lambda: (
                xbrl_paths(
                    resolve_artifacts_root(getattr(args, "artifacts_root", None))
                ).snapshots_root
            ),
            default_specs=XBRL_RELATIONS,
        )
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute XBRL CLI commands based on command line arguments."""
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
