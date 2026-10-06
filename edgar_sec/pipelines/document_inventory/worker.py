"""Per-accession process task for the S4 broker-backed worker pool.

Module-level so the spawn context can pickle it as the process task; the
response envelope and parser-only structures are released before returning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    IndexParseOutcome,
    IndexWorkItem,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.foundation.runtime.memory import reclaim

from .broker import IndexFetchFailure, IndexPageBrokerClient


@dataclass(frozen=True, slots=True)
class IndexWorkerFailure:
    """A process task failed outside parsing: an exception in the worker."""

    accession: AccessionNumber
    code: Literal["worker_error"]
    detail: str


_TypedResult = IndexParseOutcome | IndexFetchFailure | IndexWorkerFailure

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
        page = broker.fetch_index(
            item.accession, item.index_url, force_refresh=force_refresh
        )
        if isinstance(page, IndexFetchFailure):
            return page
        return parse_html_index(
            IndexPageInput(item.accession, item.index_url, page.html_bytes)
        )
    except Exception as exc:  # noqa: BLE001
        return IndexWorkerFailure(
            item.accession, "worker_error", str(exc) or type(exc).__name__
        )
    finally:
        reclaim()


def _run_task(
    item: IndexWorkItem,
    broker: IndexPageBrokerClient,
    force_refresh: bool,
) -> _TypedResult:
    """Execute one accession in a pool child; module-level for pickling."""
    return process_accession(item, broker, force_refresh=force_refresh)
