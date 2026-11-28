"""Regenerate a discovery corpus's per-filing bundles from its accession list.

Composition only: index parsing and linkbase discovery from the discovery
plane, filing parsing from the XBRL parser, writers from XBRL storage.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import gzip
import json
from pathlib import Path
import sys

from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.document_inventory.models import IndexPageInput, ParsedIndexPage
from edgar_sec.domain.sec_urls import archives_url, index_url_for
from edgar_sec.engine.document.html.normalizer import normalize_html_document
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.engine.xbrl.discovery.cohort import SeedFiling, load_seed_cohort
from edgar_sec.engine.xbrl.discovery.discovery import (
    DiscoveredLinkbase,
    LinkbaseType,
    extract_filing_linkbases,
)
from edgar_sec.engine.xbrl.parsing.filing_parser import parse_filing_xbrl
from edgar_sec.engine.xbrl.parsing.instance_parser import (
    extract_prefix_namespaces,
    parse_instance_facts,
)
from edgar_sec.engine.xbrl.parsing.linkbase_parser import parse_linkbase_bundle
from edgar_sec.engine.xbrl.schema.models import FilingXbrl
from edgar_sec.engine.xbrl.storage.storage import (
    write_calculation_arcs_parquet,
    write_declarations_parquet,
    write_definition_arcs_parquet,
    write_facts_parquet,
    write_presentation_arcs_parquet,
)
from edgar_sec.foundation.runtime.env import get_env
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.tools.xbrl_discovery.accession_lists import (
    CORPUS_NAMES,
    load_accession_list,
)

ByteFetcher = Callable[[str], bytes]

_FACTS_FILE = "facts.parquet"
_CALC_FILE = "calculation_arcs.parquet"
_PRES_FILE = "presentation_arcs.parquet"
_DEF_FILE = "definition_arcs.parquet"
_DECLARATIONS_FILE = "declarations.parquet"
_NAMESPACES_FILE = "namespaces.json"
_TEXT_FILE = "normalized_text.txt.gz"
_SOURCE_REGISTRY_FILE = "fixture_source_registry.json"


@dataclass(frozen=True, slots=True)
class BundleBuildResult:
    """One regenerated bundle: its folder, members, and source accession."""

    filing: SeedFiling
    folder: str
    bundle_dir: Path
    members: tuple[str, ...]
    fact_count: int
    source_accession: str


@dataclass(frozen=True, slots=True)
class FilingFailure:
    """One filing whose bundle could not be regenerated."""

    accession: str
    error: str


@dataclass(frozen=True, slots=True)
class CorpusRegenerationResult:
    """Outcome of one corpus regeneration run."""

    corpus: str
    output_dir: Path
    bundles: tuple[BundleBuildResult, ...]
    failures: tuple[FilingFailure, ...]


def bundle_folder(filing: SeedFiling) -> str:
    """Bundle folder name for a filing: firm, fiscal year, and form token."""
    form_token = filing.form.lower().replace("-", "")
    return f"{filing.firm.lower()}_{filing.fy}_{form_token}"


def _aggregate(
    filing: SeedFiling,
    discovered: Sequence[DiscoveredLinkbase],
    payloads: Mapping[str, bytes],
    primary_bytes: bytes | None,
) -> FilingAggregate:
    """Filing aggregate whose attachments serve the downloaded payloads."""
    attachments = tuple(
        FilingAttachment(
            attachment_id=f"{filing.accession}-{lb.filename}",
            document_type=lb.document_type,
            filename=lb.filename,
            url=lb.archive_url,
            fetcher=lambda _att, payload=payloads[lb.filename]: payload,
        )
        for lb in discovered
        if lb.filename in payloads
    )
    return FilingAggregate(
        accession=filing.accession,
        primary_cik=filing.cik,
        ciks=(filing.cik,),
        form=filing.form,
        filing_date="",
        primary_document_path=Path(filing.sec_filing_url).name,
        attachments=attachments,
        fetcher=lambda _agg: primary_bytes,
    )


def _parse_directly(
    filing: SeedFiling,
    discovered: Sequence[DiscoveredLinkbase],
    payloads: Mapping[str, bytes],
) -> FilingXbrl:
    """Fallback composition when the aggregate's linkbase view is empty."""
    by_type: dict[LinkbaseType, bytes] = {}
    instances: list[bytes] = []
    for lb in discovered:
        payload = payloads.get(lb.filename)
        if payload is None:
            continue
        if lb.linkbase_type is LinkbaseType.INSTANCE:
            instances.append(payload)
        else:
            by_type.setdefault(lb.linkbase_type, payload)
    bundle = parse_linkbase_bundle(
        cal_xml=by_type.get(LinkbaseType.CALCULATION),
        pre_xml=by_type.get(LinkbaseType.PRESENTATION),
        lab_xml=by_type.get(LinkbaseType.LABEL),
        def_xml=by_type.get(LinkbaseType.DEFINITION),
        xsd=by_type.get(LinkbaseType.SCHEMA),
    )
    facts: tuple = ()
    namespaces: tuple[tuple[str, str], ...] = ()
    for payload in instances:
        parsed_facts = parse_instance_facts(payload, filing.accession)
        if parsed_facts:
            facts = parsed_facts
            namespaces = tuple(sorted(extract_prefix_namespaces(payload).items()))
            break
    return FilingXbrl(
        accession=filing.accession,
        cik=filing.cik,
        facts=facts,
        linkbases=bundle,
        namespaces=namespaces,
    )


def build_bundle(
    filing: SeedFiling,
    discovered: Sequence[DiscoveredLinkbase],
    payloads: Mapping[str, bytes],
    primary_bytes: bytes | None,
    bundle_dir: Path,
) -> BundleBuildResult:
    """Build one filing's bundle directory from downloaded payloads."""
    aggregate = _aggregate(filing, discovered, payloads, primary_bytes)
    parsed = parse_filing_xbrl(aggregate)
    if not parsed.facts and not parsed.linkbases.calculation_arcs and payloads:
        parsed = _parse_directly(filing, discovered, payloads)

    bundle_dir.mkdir(parents=True, exist_ok=True)
    members: list[str] = []
    write_facts_parquet(parsed.facts, bundle_dir / _FACTS_FILE)
    members.append(_FACTS_FILE)
    write_calculation_arcs_parquet(
        parsed.linkbases.calculation_arcs, bundle_dir / _CALC_FILE
    )
    members.append(_CALC_FILE)
    write_presentation_arcs_parquet(
        parsed.linkbases.presentation_arcs, bundle_dir / _PRES_FILE
    )
    members.append(_PRES_FILE)
    write_definition_arcs_parquet(
        parsed.linkbases.definition_arcs, bundle_dir / _DEF_FILE
    )
    members.append(_DEF_FILE)
    write_declarations_parquet(
        parsed.linkbases.declarations, bundle_dir / _DECLARATIONS_FILE
    )
    members.append(_DECLARATIONS_FILE)
    (bundle_dir / _NAMESPACES_FILE).write_text(
        canonical_json(dict(parsed.namespaces)), encoding="utf-8"
    )
    members.append(_NAMESPACES_FILE)
    if primary_bytes is not None:
        text = normalize_html_document(primary_bytes.decode("utf-8", errors="replace"))
        with open(bundle_dir / _TEXT_FILE, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
                gz.write(text.encode("utf-8"))
        members.append(_TEXT_FILE)

    fact_accessions = {str(fact.accession) for fact in parsed.facts}
    source_accession = (
        fact_accessions.pop() if len(fact_accessions) == 1 else str(filing.accession)
    )
    return BundleBuildResult(
        filing=filing,
        folder=bundle_dir.name,
        bundle_dir=bundle_dir,
        members=tuple(members),
        fact_count=len(parsed.facts),
        source_accession=source_accession,
    )


def _source_registry_entry(result: BundleBuildResult) -> dict[str, object]:
    """Fixture source registry row for one regenerated bundle."""
    filing = result.filing
    source_matches = result.source_accession == str(filing.accession)
    return {
        "folder": result.folder,
        "firm": filing.firm,
        "cohort_accession": str(filing.accession),
        "cohort_fiscal_year": filing.fy,
        "source_accession": result.source_accession,
        "source_filing_fiscal_year": filing.fy,
        "reported_fiscal_year": filing.fy,
        "source_matches_cohort": source_matches,
        "source_cik_matches_registrant": True,
        "provenance_status": "VERIFIED" if source_matches else "UNVERIFIED",
    }


def _primary_url(filing: SeedFiling, page: ParsedIndexPage) -> str | None:
    """Archive URL of the filing's primary document, from its index page."""
    for entry in page.entries:
        if (
            entry.document_type
            and entry.document_type.strip().upper() == filing.form.upper()
            and entry.filename
            and entry.filename.lower().endswith((".htm", ".html", ".txt"))
        ):
            return entry.archive_url or archives_url(
                filing.cik, page.accession.normalized, entry.filename
            )
    return None


def regenerate_filing(
    filing: SeedFiling,
    corpus_dir: Path,
    fetch: ByteFetcher,
    *,
    folder: str | None = None,
) -> BundleBuildResult:
    """Regenerate one filing's bundle: index, linkbases, primary document."""
    index_url = index_url_for(filing.accession, filing.cik)
    page_input = IndexPageInput(
        accession=filing.accession,
        source_url=index_url,
        response_bytes=fetch(index_url),
    )
    outcome = parse_html_index(page_input)
    if not isinstance(outcome, ParsedIndexPage):
        raise ValueError(f"failed to parse index page for {filing.accession}")
    discovered = extract_filing_linkbases(outcome, filing.cik)
    payloads = {lb.filename: fetch(lb.archive_url) for lb in discovered}
    primary_url = _primary_url(filing, outcome)
    primary_bytes = fetch(primary_url) if primary_url is not None else None
    return build_bundle(
        filing,
        discovered,
        payloads,
        primary_bytes,
        corpus_dir / (folder or bundle_folder(filing)),
    )


def regenerate_corpus(
    corpus: str,
    filings: Sequence[SeedFiling],
    output_root: Path,
    fetch: ByteFetcher,
    *,
    folder_overrides: Mapping[str, str] | None = None,
) -> CorpusRegenerationResult:
    """Regenerate every filing's bundle under an untracked corpus root."""
    corpus_dir = output_root / corpus
    corpus_dir.mkdir(parents=True, exist_ok=True)
    bundles: list[BundleBuildResult] = []
    failures: list[FilingFailure] = []
    overrides = folder_overrides or {}
    for filing in filings:
        try:
            bundles.append(
                regenerate_filing(
                    filing,
                    corpus_dir,
                    fetch,
                    folder=overrides.get(str(filing.accession)),
                )
            )
        except Exception as exc:
            failures.append(FilingFailure(str(filing.accession), str(exc)))
    registry = {"bundles": [_source_registry_entry(b) for b in bundles]}
    (corpus_dir / _SOURCE_REGISTRY_FILE).write_text(
        json.dumps(registry, indent=1) + "\n", encoding="utf-8"
    )
    return CorpusRegenerationResult(
        corpus=corpus,
        output_dir=corpus_dir,
        bundles=tuple(bundles),
        failures=tuple(failures),
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Regenerate discovery corpus bundles from accession lists.",
    )
    parser.add_argument(
        "--corpus",
        choices=(*CORPUS_NAMES, "all"),
        default="all",
        help="Corpus to regenerate (default: all).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Untracked corpus root; bundles land in <root>/<corpus>/<folder>.",
    )
    parser.add_argument(
        "--accession-list",
        type=Path,
        default=None,
        help="Custom accession-list JSON (SeedFiling schema); single-corpus only.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of filings per corpus.",
    )
    parser.add_argument(
        "--folder-map",
        type=Path,
        default=None,
        help="Optional JSON map of accession -> bundle folder override.",
    )
    parser.add_argument(
        "--allow-in-repo-output",
        action="store_true",
        help="Permit an output root inside the repository tree (not recommended).",
    )
    parser.add_argument(
        "--user-agent",
        type=str,
        default=None,
        help="Custom User-Agent header for live SEC requests.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: regenerate the named corpora into the output root."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[3]
    output_root = args.output_root.resolve()
    if not args.allow_in_repo_output and (
        output_root == repo_root or repo_root in output_root.parents
    ):
        parser.error("--output-root must be an untracked root outside the repo tree")

    folder_overrides: Mapping[str, str] = {}
    if args.folder_map is not None:
        folder_overrides = json.loads(args.folder_map.read_text(encoding="utf-8"))

    corpora = CORPUS_NAMES if args.corpus == "all" else (args.corpus,)
    if args.accession_list is not None and len(corpora) != 1:
        parser.error("--accession-list requires a single --corpus")

    user_agent = (
        args.user_agent or get_env("SEC_USER_AGENT") or "SampleApp contact@example.com"
    )
    client = SecHttpClient(user_agent=user_agent)

    def fetch(url: str) -> bytes:
        kind = "index_page" if url.endswith(("-index.htm", "-index.html")) else "xbrl"
        return client.get_bytes(url, content_kind=kind)

    failed = 0
    for corpus in corpora:
        filings = (
            load_seed_cohort(args.accession_list)
            if args.accession_list is not None
            else load_accession_list(corpus)
        )
        if args.limit is not None and args.limit > 0:
            filings = filings[: args.limit]
        result = regenerate_corpus(
            corpus, filings, output_root, fetch, folder_overrides=folder_overrides
        )
        print(
            f"{corpus}: {len(result.bundles)} bundles regenerated, "
            f"{len(result.failures)} failures -> {result.output_dir}"
        )
        for failure in result.failures:
            print(f"  FAILED {failure.accession}: {failure.error}")
        failed += len(result.failures)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
