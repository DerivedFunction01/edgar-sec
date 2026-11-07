"""Per-accession process task for the broker-backed worker pool.

Module-level so the spawn context can pickle it; envelopes and parser-only
structures are released before returning. Summary-routed accessions try
FilingSummary, the XBRL package, then the index page, in one task.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from edgar_sec.domain.document_inventory.models import (
    EnumeratedDocuments,
    EnumerationInput,
    EnumerationOutcome,
    IndexPageInput,
    IndexParseOutcome,
    IndexWorkItem,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.document_inventory.models import ParsedIndexPage
from edgar_sec.domain.sec_urls import (
    FILING_SUMMARY_DOCUMENT,
    archives_url,
    index_json_url_for,
    parse_archive_url,
    xbrl_package_url_for,
)
from edgar_sec.engine.filing_summary.parser import (
    parse_filing_summary,
    parse_xbrl_package,
)
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.engine.index_pages.parser_json import parse_json_index
from edgar_sec.foundation.runtime.memory import reclaim

from .broker import IndexFetchFailure, IndexPageBrokerClient


@dataclass(frozen=True, slots=True)
class IndexWorkerFailure:
    """A process task failed outside parsing: an exception in the worker."""

    accession: AccessionNumber
    code: Literal["worker_error"]
    detail: str
    vehicle: Literal["index", "summary", "package"] = "index"


_TypedResult = (
    IndexParseOutcome | EnumerationOutcome | IndexFetchFailure | IndexWorkerFailure
)

__all__ = ["IndexWorkerFailure", "RECLAIM_INTERVAL", "process_accession", "_run_task"]

#: Process children are recycled after this many tasks to bound heap growth.
RECLAIM_INTERVAL = 64


def process_accession(
    item: IndexWorkItem,
    broker: IndexPageBrokerClient,
    *,
    force_refresh: bool = False,
) -> _TypedResult:
    """Fetch and parse one accession, returning exactly one typed result.

    Module-level so the spawn context can pickle it as the process task; the
    response envelope and parser-only structures are released before returning.
    """
    try:
        if item.vehicle == "summary" and _can_enumerate(item):
            return _process_via_summary(item, broker, force_refresh=force_refresh)
        return _process_via_index(item, broker, force_refresh=force_refresh)
    except Exception as exc:  # noqa: BLE001
        return IndexWorkerFailure(
            item.accession,
            "worker_error",
            str(exc) or type(exc).__name__,
            vehicle=item.vehicle,
        )
    finally:
        reclaim()


def _can_enumerate(item: IndexWorkItem) -> bool:
    return bool(item.archive_cik and item.primary_document and item.form)


def _process_via_index(
    item: IndexWorkItem,
    broker: IndexPageBrokerClient,
    *,
    force_refresh: bool,
) -> IndexParseOutcome | IndexFetchFailure:
    json_outcome = _process_via_index_json(item, broker, force_refresh=force_refresh)
    if json_outcome is not None:
        return json_outcome
    page = broker.fetch_index(
        item.accession, item.index_url, force_refresh=force_refresh
    )
    if isinstance(page, IndexFetchFailure):
        return page
    return parse_html_index(
        IndexPageInput(item.accession, item.index_url, page.html_bytes)
    )


def _process_via_index_json(
    item: IndexWorkItem,
    broker: IndexPageBrokerClient,
    *,
    force_refresh: bool,
) -> ParsedIndexPage | None:
    parts = parse_archive_url(item.index_url)
    if parts is None:
        return None
    json_url = index_json_url_for(item.accession, parts.archive_cik)
    try:
        fetched = broker.fetch_document(
            item.accession, json_url, force_refresh=force_refresh
        )
    except Exception:  # noqa: BLE001
        return None
    if isinstance(fetched, IndexFetchFailure):
        return None
    outcome = parse_json_index(
        IndexPageInput(item.accession, json_url, fetched.payload_bytes)
    )
    return outcome if isinstance(outcome, ParsedIndexPage) else None


def _enumeration_input(
    item: IndexWorkItem, url: str, payload: bytes
) -> EnumerationInput:
    return EnumerationInput(
        accession=item.accession,
        source_url=url,
        response_bytes=payload,
        archive_cik=item.archive_cik or "",
        form=item.form or "",
        primary_document=item.primary_document or "",
        is_inline_xbrl=item.is_inline_xbrl,
    )


def _process_via_summary(
    item: IndexWorkItem,
    broker: IndexPageBrokerClient,
    *,
    force_refresh: bool,
) -> _TypedResult:
    summary_url = archives_url(
        item.archive_cik, item.accession, FILING_SUMMARY_DOCUMENT
    )
    fetched = broker.fetch_document(
        item.accession, summary_url, force_refresh=force_refresh
    )
    if isinstance(fetched, IndexFetchFailure):
        if fetched.status_code != 404:
            return replace(fetched, vehicle="summary")
    else:
        outcome = parse_filing_summary(
            _enumeration_input(item, summary_url, fetched.payload_bytes)
        )
        if isinstance(outcome, EnumeratedDocuments):
            return outcome

    package_url = xbrl_package_url_for(item.archive_cik, item.accession)
    fetched = broker.fetch_document(
        item.accession, package_url, force_refresh=force_refresh
    )
    if isinstance(fetched, IndexFetchFailure):
        if fetched.status_code != 404:
            return replace(fetched, vehicle="package")
    else:
        outcome = parse_xbrl_package(
            _enumeration_input(item, package_url, fetched.payload_bytes)
        )
        if isinstance(outcome, EnumeratedDocuments):
            return outcome

    return _process_via_index(item, broker, force_refresh=force_refresh)


def _run_task(
    item: IndexWorkItem,
    broker: IndexPageBrokerClient,
    force_refresh: bool,
) -> _TypedResult:
    """Execute one accession in a pool child; module-level for pickling."""
    return process_accession(item, broker, force_refresh=force_refresh)
