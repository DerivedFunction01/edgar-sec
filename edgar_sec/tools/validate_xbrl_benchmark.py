"""CLI benchmark tool for multi-firm XBRL lattice verification and robustness testing."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from edgar_sec.engine.xbrl.review.benchmark import (
    BenchmarkReport,
    BenchmarkTestResult,
    run_benchmark,
)
from edgar_sec.engine.xbrl.discovery.cohort import load_seed_cohort
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.xbrl_review.paths import default_seed_cohort_path, xbrl_paths

__all__ = [
    "BenchmarkReport",
    "BenchmarkTestResult",
    "main",
    "run_benchmark",
]


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for benchmark runner."""
    parser = argparse.ArgumentParser(
        description="Run multi-firm XBRL lattice robustness benchmark across seed cohort.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Optional destination path for benchmark report JSON.",
    )
    parser.add_argument(
        "--cohort-file",
        type=Path,
        default=None,
        help="Optional path to custom seed cohort JSON.",
    )
    parser.add_argument(
        "--taxonomy-dir",
        type=Path,
        default=None,
        help="Optional path to custom taxonomy directory.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-test execution details.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for XBRL robustness benchmark runner."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    cohort_source = (
        Path(args.cohort_file) if args.cohort_file else default_seed_cohort_path()
    )
    if not cohort_source.exists():
        sys.stderr.write(f"Cohort file not found: {cohort_source}\n")
        return 1

    cohort = load_seed_cohort(cohort_source)
    tax = load_domain_taxonomy(args.taxonomy_dir)
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    solver = XbrlConstraintSolver(kb)

    report = run_benchmark(cohort, solver)

    sys.stdout.write(
        f"\n{'=' * 60}\n"
        f"XBRL LATTICE MULTI-FIRM ROBUSTNESS BENCHMARK REPORT\n"
        f"{'=' * 60}\n"
        f"Firms evaluated: {report.firm_count}\n"
        f"Total tests:     {report.total_tests}\n"
        f"Passed:          {report.passed_tests}\n"
        f"Failed:          {report.failed_tests}\n"
        f"Accuracy:        {report.accuracy_pct}%\n"
        f"Total latency:   {round(report.total_latency_ms, 2)} ms "
        f"({round(report.total_latency_ms / max(report.total_tests, 1), 3)} ms/test)\n"
        f"{'-' * 60}\n"
        f"Battery Breakdown:\n"
    )
    for b_id, stats in sorted(report.battery_stats.items()):
        pct = round(stats["passed"] / max(stats["total"], 1) * 100.0, 1)
        sys.stdout.write(
            f"  [{b_id}] Passed {stats['passed']}/{stats['total']} ({pct}%)\n"
        )

    sys.stdout.write(f"{'-' * 60}\nResolution Tiers:\n")
    for tier, count in sorted(report.tier_counts.items()):
        sys.stdout.write(f"  {tier}: {count}\n")
    sys.stdout.write(f"{'=' * 60}\n\n")

    if args.verbose:
        for r in report.results:
            status = "PASS" if r.passed else "FAIL"
            sys.stdout.write(
                f"[{status}] {r.battery} {r.firm} {r.target} tier={r.tier} "
                f"exp={r.expected} act={r.actual} ({round(r.latency_ms, 2)}ms)\n"
            )

    out_path = args.output or (xbrl_paths().transient_root / "benchmark_report.json")
    atomic_write_json(out_path, report.to_dict(), indent=2)
    sys.stdout.write(f"Report written to: {out_path}\n")

    return 0 if report.failed_tests == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
