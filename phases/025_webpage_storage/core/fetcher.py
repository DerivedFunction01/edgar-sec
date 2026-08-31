"""Archive document acquisition implementations for Phase 2.5."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from defs.sec_http import HttpMetrics, SecHttpClient
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
        self._fixture_paths = tuple(Path(p) for p in fixture_paths)
        self._local = threading.local()
        self._all_executors: list[SqlExecutor] = []
        self._lock = threading.Lock()

    def _get_executors(self) -> list[SqlExecutor]:
        if not hasattr(self._local, "executors"):
            execs = [
                make_sql_executor(path, dialect="sqlite")
                for path in self._fixture_paths
            ]
            self._local.executors = execs
            with self._lock:
                self._all_executors.extend(execs)
        return self._local.executors

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
            for executor in self._get_executors():
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

    def __getstate__(self) -> dict[str, object]:
        return {"_fixture_paths": self._fixture_paths}

    def __setstate__(self, state: dict[str, object]) -> None:
        self._fixture_paths = state["_fixture_paths"]  # type: ignore[assignment]
        self._local = threading.local()
        self._all_executors = []
        self._lock = threading.Lock()

    def close(self) -> None:
        """Close the fixture database connections owned by this fetcher."""
        with self._lock:
            for executor in self._all_executors:
                with suppress(Exception):
                    executor.close()
            self._all_executors.clear()


class LiveSecArchiveFetcher:
    """Acquire archive bytes through the shared SEC HTTP client."""

    def __init__(self, http_client: SecHttpClient) -> None:
        self._http_client = http_client

    def __getstate__(self) -> dict[str, object]:
        return {
            "user_agent": self._http_client.user_agent,
            "cache_dir": self._http_client.cache_dir,
        }

    def __setstate__(self, state: dict[str, object]) -> None:
        from defs.sec_http import make_sec_http_client

        self._http_client = make_sec_http_client(
            user_agent=state.get("user_agent"),  # type: ignore[arg-type]
            cache_dir=state.get("cache_dir"),  # type: ignore[arg-type]
        )

    @property
    def metrics(self) -> HttpMetrics:
        return self._http_client.metrics

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
    broker_socket: str | Path | None = None,
) -> ArchiveFetcher:
    """Construct the configured offline fixture or live SEC fetcher.

    ``broker_socket`` selects the managed broker path for live acquisition:
    workers route archive URLs through the broker instead of constructing
    their own SEC client, so all live requests share one aggregate rate
    limiter. ``broker_socket`` is ignored for fixture mode.

    ``mode`` accepts ``"fixture"`` for offline lookup and ``"live"`` or
    ``"production"`` for live SEC acquisition.
    """
    normalized_mode = mode.strip().lower()
    if normalized_mode == "fixture":
        if not fixture_paths:
            raise ValueError("fixture mode requires fixture_paths")
        return FixtureArchiveFetcher(fixture_paths)
    if normalized_mode in ("live", "production"):
        if broker_socket is not None:
            from defs.sec_http.broker import SecBrokerClient

            return BrokerArchiveFetcher(SecBrokerClient(broker_socket))
        if http_client is None:
            raise ValueError("live mode requires http_client")
        return LiveSecArchiveFetcher(http_client)
    raise ValueError(f"unsupported archive fetcher mode: {mode!r}")


class BrokerArchiveFetcher:
    """Adapt the SEC broker RPC to the ``ArchiveFetcher`` protocol.

    Worker processes never construct a production SEC client; they route
    every archive URL through the broker, which owns the single shared rate
    limiter, cache, failure ledger, and metrics.
    """

    def __init__(self, broker_client: Any) -> None:
        self._broker = broker_client

    @property
    def metrics(self) -> Any:
        return getattr(self._broker, "metrics", None)

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        try:
            result = self._broker.fetch(locator.archive_url)
        except Exception as exc:  # noqa: BLE001 - client errors are per-document failures
            return FetchResult(
                locator=locator, payload=None, status="failed", error=str(exc)
            )
        status = result.get("status")
        if status != "ok":
            return FetchResult(
                locator=locator,
                payload=None,
                status="failed",
                error=result.get("error") or "broker reported failure",
            )
        payload = result.get("payload")
        if payload is None:
            return FetchResult(
                locator=locator,
                payload=None,
                status="failed",
                error="broker returned no payload",
            )
        return FetchResult(locator=locator, payload=payload, status="ok")

    def close(self) -> None:
        close = getattr(self._broker, "close", None)
        if close is not None:
            with suppress(Exception):
                close()


__all__ = [
    "ArchiveFetcher",
    "BrokerArchiveFetcher",
    "FixtureArchiveFetcher",
    "LiveSecArchiveFetcher",
    "make_archive_fetcher",
]
