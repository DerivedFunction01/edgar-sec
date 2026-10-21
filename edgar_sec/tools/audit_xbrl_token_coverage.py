"""CLI tool for auditing XBRL concept modelled-ness across seed bundles."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
import sys

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.discovery.cohort import load_seed_cohort
from edgar_sec.engine.xbrl.discovery.fixture_miner import (
    BundleFacts,
    build_modelledness_report,
)
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.xbrl_review.paths import default_seed_cohort_path


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for the token coverage audit."""
    parser = argparse.ArgumentParser(
        description="Audit XBRL concept modelled-ness across seed bundles.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Destination path for the audit report JSON.",
    )
    parser.add_argument(
        "--cohort-file",
        type=Path,
        default=None,
        help="Optional path to custom seed cohort JSON.",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="Directory holding the seed bundle folders.",
    )
    parser.add_argument(
        "--min-firms",
        type=int,
        default=3,
        help="Minimum firm support for the residual-based candidate rule.",
    )
    parser.add_argument(
        "--min-sics",
        type=int,
        default=2,
        help="Minimum SIC support for the residual-based candidate rule.",
    )
    return parser


def _load_bundle(fixtures_dir: Path, firm: str, sic_code: int) -> BundleFacts | None:
    """Load one firm's seed bundle tables, or None when absent."""
    matches = sorted(fixtures_dir.glob(f"{firm.lower()}_*_10k"))
    if not matches or not (matches[0] / "facts.parquet").exists():
        return None
    root = matches[0]

    def _optional(name: str) -> pq.Table | None:
        path = root / name
        return pq.read_table(path) if path.exists() else None

    return BundleFacts(
        firm=firm,
        sic_code=str(sic_code),
        facts=pq.read_table(root / "facts.parquet"),
        calculation_arcs=_optional("calculation_arcs.parquet"),
        presentation_arcs=_optional("presentation_arcs.parquet"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for the XBRL token coverage audit."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    paths = resolve_xbrl_paths()
    cohort_source = args.cohort_file or default_seed_cohort_path()
    if not cohort_source.exists():
        sys.stderr.write(f"Cohort file not found: {cohort_source}\n")
        return 1
    fixtures_dir = args.fixtures_dir or (
        paths.repo_root / "tests" / "fixtures" / "xbrl" / "seed"
    )
    if not fixtures_dir.exists():
        sys.stderr.write(f"Fixtures directory not found: {fixtures_dir}\n")
        return 1

    cohort = load_seed_cohort(cohort_source)
    bundles = [
        bundle
        for filing in cohort
        if (bundle := _load_bundle(fixtures_dir, filing.firm, filing.sic_code))
        is not None
    ]
    if not bundles:
        sys.stderr.write(f"No seed bundles found under: {fixtures_dir}\n")
        return 1

    lexicon = TokenLexicon.load_json(paths.default_token_lexicon_path)
    report = build_modelledness_report(
        bundles,
        lexicon,
        min_firms=args.min_firms,
        min_sics=args.min_sics,
    )

    out_path = args.output or (
        paths.artifacts_root / "xbrl" / "token_coverage_report.json"
    )
    atomic_write_json(out_path, asdict(report), indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
