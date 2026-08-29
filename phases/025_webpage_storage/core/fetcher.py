"""Archive document acquisition implementations for Phase 2.5."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from defs.sec_http import SecHttpClient
from defs.sql import (
    Compare,
    ComparisonOp,
    Select,
    SqlExecutor,
    Table,
    col,
    make_sql_executor,
    param,
)

from .schemas import (
    DOCUMENT_BLOBS_TABLE,
    DocumentLocator,
    FetchResult,
    RawDocumentBlob,
    decompress_payload,
    doc_id,
)


@runtime_checkable
class ArchiveFetcher(Protocol):
    """Fetch one archive document without deciding how it is persisted."""

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        """Acquire the bytes identified by ``locator``."""


class FixtureArchiveFetcher:
    """Look up compressed archive blobs in one or more SQLite fixtures."""

    def __init__(self, fixture_paths: Iterable[str | Path]) -> None:
        self._executors: list[SqlExecutor] = [
            make_sql_executor(path, dialect="sqlite") for path in fixture_paths
        ]

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        expected_doc_id = doc_id(locator.accession, locator.document_path)
        query = Select(
            source=Table(DOCUMENT_BLOBS_TABLE),
            projection=(
                col("doc_id"),
                col("accession"),
                col("document_path"),
                col("byte_size"),
                col("mime_type"),
                col("raw_payload"),
            ),
            where=Compare(col("doc_id"), ComparisonOp.EQ, param(expected_doc_id)),
            limit=1,
        )

        try:
            for executor in self._executors:
                row = executor.query_one(executor.compiler.compile(query))
                if row is None:
                    continue
                blob = RawDocumentBlob.from_row(row)
                return FetchResult(
                    locator=locator,
                    payload=decompress_payload(blob.raw_payload),
                    status="ok",
                )
        except Exception as exc:  # noqa: BLE001 - fetch failures become result statuses
            return FetchResult(
                locator=locator, payload=None, status="failed", error=str(exc)
            )

        return FetchResult(locator=locator, payload=None, status="missing")

    def close(self) -> None:
        """Close the fixture database connections owned by this fetcher."""
        for executor in self._executors:
            executor.close()


class LiveSecArchiveFetcher:
    """Acquire archive bytes through the shared SEC HTTP client."""

    def __init__(self, http_client: SecHttpClient) -> None:
        self._http_client = http_client

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        try:
            payload = self._http_client.get_bytes(locator.archive_url)
        except Exception as exc:  # noqa: BLE001 - client errors are per-document failures
            return FetchResult(
                locator=locator, payload=None, status="failed", error=str(exc)
            )
        return FetchResult(locator=locator, payload=payload, status="ok")


def make_archive_fetcher(
    mode: str,
    fixture_paths: Sequence[str | Path] | None = None,
    http_client: SecHttpClient | None = None,
) -> ArchiveFetcher:
    """Construct the configured offline fixture or live SEC fetcher."""
    normalized_mode = mode.strip().lower()
    if normalized_mode == "fixture":
        if not fixture_paths:
            raise ValueError("fixture mode requires fixture_paths")
        return FixtureArchiveFetcher(fixture_paths)
    if normalized_mode == "live":
        if http_client is None:
            raise ValueError("live mode requires http_client")
        return LiveSecArchiveFetcher(http_client)
    raise ValueError(f"unsupported archive fetcher mode: {mode!r}")


__all__ = [
    "ArchiveFetcher",
    "FixtureArchiveFetcher",
    "LiveSecArchiveFetcher",
    "make_archive_fetcher",
]
