"""Archive document acquisition implementations for Phase 2.5."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from defs.filing_identity import (
    accession_hyphenated,
    full_submission_url_for,
    normalize_accession,
    parse_archive_url,
)
from defs.sec_documents.sgml import (
    extract_target_sub_document,
    has_sgml_documents,
)
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
    decompress_payload,
    doc_id,
)


@runtime_checkable
class ArchiveFetcher(Protocol):
    """Fetch one archive document without deciding how it is persisted."""

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        """Acquire the bytes identified by ``locator``."""


def is_stub_document_path(document_path: str | None) -> bool:
    """True when the document path is a placeholder/stub rather than substantive filing."""
    if not document_path:
        return True
    lowered = document_path.strip().lower()
    return lowered.endswith(("0001.txt", "0001.htm", "0000.txt", "0000.htm"))


def extract_from_sgml_envelope(
    raw_payload: bytes,
    locator: DocumentLocator,
) -> bytes | None:
    """Extract the target sub-document if the payload is an SGML submission envelope.

    Scans the envelope and materializes only the resolved target's payload;
    block-less payloads (plain documents) are returned unchanged.
    """
    if not raw_payload:
        return None
    head = raw_payload[:1000].lower()
    if b"<document>" not in head and b"<submission>" not in head:
        return raw_payload
    if not has_sgml_documents(raw_payload):
        return raw_payload

    form_val = locator.form.strip().upper() if locator.form else None
    targets = ()
    if form_val:
        targets = (
            (form_val, f"{form_val}/A", form_val[:-2])
            if form_val.endswith("/A")
            else (form_val, f"{form_val}/A")
        )
    return extract_target_sub_document(
        raw_payload,
        target_types=targets,
        primary_filename=locator.document_path,
        fallback_to_sequence_one=True,
    )


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
            projection=(col("raw_payload"),),
            where=Compare(col("doc_id"), ComparisonOp.EQ, param(expected_doc_id)),
            limit=1,
        )

        try:
            for executor in self._get_executors():
                row = executor.query_one(executor.compiler.compile(query))
                if row is not None and row.get("raw_payload") is not None:
                    payload = decompress_payload(row["raw_payload"])
                    extracted = extract_from_sgml_envelope(payload, locator)
                    if extracted is not None:
                        return FetchResult(
                            locator=locator,
                            payload=extracted,
                            status="ok",
                        )

                # Fallback to full submission blob if present in fixture
                canonical = normalize_accession(locator.accession)
                if canonical:
                    dashed = accession_hyphenated(canonical)
                    full_doc_id = doc_id(locator.accession, f"{dashed}.txt")
                    query_full = Select(
                        source=Table(DOCUMENT_BLOBS_TABLE),
                        projection=(col("raw_payload"),),
                        where=Compare(
                            col("doc_id"), ComparisonOp.EQ, param(full_doc_id)
                        ),
                        limit=1,
                    )
                    row_full = executor.query_one(executor.compiler.compile(query_full))
                    if row_full is not None:
                        sgml_payload = decompress_payload(row_full["raw_payload"])
                        extracted = extract_from_sgml_envelope(sgml_payload, locator)
                        if extracted is not None:
                            return FetchResult(
                                locator=locator,
                                payload=extracted,
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
        parts = parse_archive_url(locator.archive_url)
        full_sub_url = (
            full_submission_url_for(parts.archive_cik, locator.accession)
            if parts
            else None
        )

        is_stub = is_stub_document_path(locator.document_path)
        primary_error = None

        if not is_stub:
            try:
                payload = self._http_client.get_bytes(locator.archive_url)
                extracted = extract_from_sgml_envelope(payload, locator)
                if extracted is not None:
                    return FetchResult(locator=locator, payload=extracted, status="ok")
            except Exception as exc:  # noqa: BLE001 - client errors fall back to full submission
                primary_error = str(exc)

        # Fallback to full SGML submission bundle if direct fetch failed or was a stub
        if full_sub_url and full_sub_url != locator.archive_url:
            try:
                sgml_payload = self._http_client.get_bytes(full_sub_url)
                extracted = extract_from_sgml_envelope(sgml_payload, locator)
                if extracted is not None:
                    return FetchResult(locator=locator, payload=extracted, status="ok")
                return FetchResult(
                    locator=locator,
                    payload=None,
                    status="failed",
                    error=f"sgml_subdocument_not_found (form={locator.form})",
                )
            except Exception as exc:  # noqa: BLE001
                err = primary_error or str(exc)
                return FetchResult(
                    locator=locator, payload=None, status="failed", error=err
                )

        return FetchResult(
            locator=locator,
            payload=None,
            status="failed",
            error=primary_error or "fetch failed",
        )


def make_archive_fetcher(
    mode: str,
    fixture_paths: Sequence[str | Path] | None = None,
    http_client: SecHttpClient | None = None,
    broker_socket: str | Path | None = None,
) -> ArchiveFetcher:
    """Construct the configured offline fixture or live SEC fetcher."""
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
    """Adapt the SEC broker RPC to the ``ArchiveFetcher`` protocol."""

    def __init__(self, broker_client: Any) -> None:
        self._broker = broker_client

    @property
    def metrics(self) -> Any:
        return getattr(self._broker, "metrics", None)

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        parts = parse_archive_url(locator.archive_url)
        full_sub_url = (
            full_submission_url_for(parts.archive_cik, locator.accession)
            if parts
            else None
        )

        is_stub = is_stub_document_path(locator.document_path)
        primary_error = None

        if not is_stub:
            try:
                result = self._broker.fetch(locator.archive_url)
                if result.get("status") == "ok" and result.get("payload") is not None:
                    extracted = extract_from_sgml_envelope(result["payload"], locator)
                    if extracted is not None:
                        return FetchResult(
                            locator=locator, payload=extracted, status="ok"
                        )
                else:
                    primary_error = result.get("error") or "broker reported failure"
            except Exception as exc:  # noqa: BLE001
                primary_error = str(exc)

        # Fallback to full SGML submission bundle if direct fetch failed or was a stub
        if full_sub_url and full_sub_url != locator.archive_url:
            try:
                result = self._broker.fetch(full_sub_url)
                if result.get("status") == "ok" and result.get("payload") is not None:
                    extracted = extract_from_sgml_envelope(result["payload"], locator)
                    if extracted is not None:
                        return FetchResult(
                            locator=locator, payload=extracted, status="ok"
                        )
                    return FetchResult(
                        locator=locator,
                        payload=None,
                        status="failed",
                        error=f"sgml_subdocument_not_found (form={locator.form})",
                    )
                err = primary_error or result.get("error") or "broker reported failure"
                return FetchResult(
                    locator=locator, payload=None, status="failed", error=err
                )
            except Exception as exc:  # noqa: BLE001
                err = primary_error or str(exc)
                return FetchResult(
                    locator=locator, payload=None, status="failed", error=err
                )

        return FetchResult(
            locator=locator,
            payload=None,
            status="failed",
            error=primary_error or "fetch failed",
        )

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
    "extract_from_sgml_envelope",
    "is_stub_document_path",
    "make_archive_fetcher",
]
