"""CLI tool for initializing and seeding XBRL linkbase Parquet tables."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from edgar_sec.domain.document_inventory.models import IndexPageInput, ParsedIndexPage
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.engine.xbrl.discovery.cohort import (
    SeedFiling,
    load_seed_cohort,
)
from edgar_sec.engine.xbrl.discovery.discovery import (
    DiscoveredLinkbase,
    extract_filing_linkbases,
)
from edgar_sec.engine.xbrl.discovery.fetcher import fetch_cohort_linkbases
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.storage.storage import write_linkbase_parquet
from edgar_sec.foundation.runtime.env import get_env
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.pipelines.xbrl_review.paths import default_seed_cohort_path


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Initialize and seed XBRL linkbase Parquet catalog from SEC or fixtures.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Destination path for linkbases.parquet.",
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=None,
        help="Custom root directory for artifacts.",
    )
    parser.add_argument(
        "--cohort-file",
        type=Path,
        default=None,
        help="Path to an optional custom seed cohort JSON file.",
    )
    parser.add_argument(
        "--use-fixtures",
        action="store_true",
        help="Run offline using index page fixtures instead of live SEC HTTP requests.",
    )
    parser.add_argument(
        "--fixture-html",
        type=Path,
        default=None,
        help="Path to sample index.html fixture to use in offline mode.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of cohort filings to process.",
    )
    parser.add_argument(
        "--user-agent",
        type=str,
        default=None,
        help="Custom User-Agent header for live SEC requests.",
    )
    return parser


def _run_from_fixtures(
    cohort: tuple[SeedFiling, ...],
    fixture_path: Path,
) -> tuple[DiscoveredLinkbase, ...]:
    """Parse linkbases offline from an index page fixture for each cohort filing."""
    raw_html = fixture_path.read_bytes()
    results: list[DiscoveredLinkbase] = []
    for filing in cohort:
        page_input = IndexPageInput(
            accession=filing.accession,
            source_url=filing.sec_filing_url,
            response_bytes=raw_html,
        )
        outcome = parse_html_index(page_input)
        if isinstance(outcome, ParsedIndexPage):
            results.extend(extract_filing_linkbases(outcome, filing.cik))
    return tuple(results)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint orchestrating cohort linkbase discovery and storage."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    paths = resolve_xbrl_paths(artifacts_root=args.artifacts_root)
    paths.ensure_directories()
    dest = args.output

    cohort_source = args.cohort_file or default_seed_cohort_path(
        artifacts_root=args.artifacts_root
    )
    if not cohort_source.exists():
        raise FileNotFoundError(f"Cohort file not found: {cohort_source}")
    cohort = load_seed_cohort(cohort_source)
    if args.limit is not None and args.limit > 0:
        cohort = cohort[: args.limit]

    if args.use_fixtures:
        fixture_html = args.fixture_html
        if fixture_html is None:
            raise ValueError(
                "--fixture-html must be provided when --use-fixtures is set"
            )
        discovered = _run_from_fixtures(cohort, fixture_html)
    else:
        user_agent = (
            args.user_agent
            or get_env("SEC_USER_AGENT")
            or "SampleApp contact@example.com"
        )
        client = SecHttpClient(user_agent=user_agent)
        discovered = fetch_cohort_linkbases(client, cohort)

    count = write_linkbase_parquet(discovered, dest)
    print(f"Discovered {len(discovered)} linkbases across {len(cohort)} filings.")
    print(f"Persisted {count} records to {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
