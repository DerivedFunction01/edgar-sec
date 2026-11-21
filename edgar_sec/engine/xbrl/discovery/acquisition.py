"""High-throughput acquisition pipeline for cohort index pages and linkbases."""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any

from edgar_sec.domain.document_inventory.models import IndexPageInput, ParsedIndexPage
from edgar_sec.domain.sec_urls import index_url_for
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.engine.xbrl.discovery.cohort import SeedFiling
from edgar_sec.engine.xbrl.discovery.discovery import (
    DiscoveredLinkbase,
    extract_filing_linkbases,
)
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.storage.storage import write_linkbase_parquet
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.sec_http.client import SecHttpClient


@dataclass(frozen=True, slots=True)
class FilingAcquisitionResult:
    """Outcome of acquiring linkbases and documents for one seed filing."""

    filing: SeedFiling
    linkbases: tuple[DiscoveredLinkbase, ...]
    downloaded_paths: dict[str, Path]
    success: bool
    error: str | None = None


@dataclass(slots=True)
class CohortAcquisitionPipeline:
    """Orchestrates bounded-concurrency acquisition of cohort XBRL linkbases."""

    client: SecHttpClient
    cache_dir: Path | None = None
    max_workers: int | None = None

    def acquire_filing(
        self,
        filing: SeedFiling,
        *,
        download_xml: bool = False,
        fixture_bytes: bytes | None = None,
    ) -> FilingAcquisitionResult:
        """Fetch index page and optionally download linkbase XMLs for a filing."""
        url = index_url_for(filing.accession, filing.cik)
        try:
            if fixture_bytes is not None:
                raw_bytes = fixture_bytes
            else:
                raw_bytes = self.client.get_bytes(url, content_kind="index_page")
        except Exception as exc:
            return FilingAcquisitionResult(
                filing=filing,
                linkbases=(),
                downloaded_paths={},
                success=False,
                error=str(exc),
            )

        page_input = IndexPageInput(
            accession=filing.accession,
            source_url=url,
            response_bytes=raw_bytes,
        )
        outcome = parse_html_index(page_input)
        if not isinstance(outcome, ParsedIndexPage):
            return FilingAcquisitionResult(
                filing=filing,
                linkbases=(),
                downloaded_paths={},
                success=False,
                error="Failed to parse index page",
            )

        discovered = extract_filing_linkbases(outcome, filing.cik)
        downloaded: dict[str, Path] = {}

        if download_xml and self.cache_dir is not None:
            filing_cache = self.cache_dir / filing.accession.raw
            filing_cache.mkdir(parents=True, exist_ok=True)
            for lb in discovered:
                dest = filing_cache / lb.filename
                if not dest.exists():
                    try:
                        content = self.client.get_bytes(
                            lb.archive_url, content_kind="xbrl"
                        )
                        dest.write_bytes(content)
                    except Exception:
                        continue
                if dest.exists():
                    downloaded[lb.filename] = dest

        return FilingAcquisitionResult(
            filing=filing,
            linkbases=discovered,
            downloaded_paths=downloaded,
            success=True,
        )

    def acquire_cohort(
        self,
        cohort: Sequence[SeedFiling],
        *,
        download_xml: bool = False,
        output_parquet: Path | None = None,
    ) -> tuple[FilingAcquisitionResult, ...]:
        """Execute acquisition across an entire cohort with bounded concurrency."""
        results: list[FilingAcquisitionResult] = []
        all_linkbases: list[DiscoveredLinkbase] = []
        workers = (
            self.max_workers
            if self.max_workers is not None
            else max(1, derive_resources().workers)
        )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self.acquire_filing, f, download_xml=download_xml): f
                for f in cohort
            }
            for i, fut in enumerate(as_completed(futures), 1):
                res = fut.result()
                results.append(res)
                if res.success:
                    all_linkbases.extend(res.linkbases)
                if i % 50 == 0:
                    reclaim()

        if output_parquet is not None and all_linkbases:
            write_linkbase_parquet(all_linkbases, output_parquet)

        return tuple(results)
