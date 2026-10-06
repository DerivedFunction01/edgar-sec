"""The archive fetcher seam: acquire document bytes, decide nothing about storage.

A fetcher reports what happened; it never writes a checkpoint or judges a payload, so
the same one serves a worker, the fixture builder, and review.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from edgar_sec.domain.document.acquisition import (
    AcquiredSubmission,
    AcquisitionSource,
    AcquisitionSourceKind,
    BundleFetchResult,
    FetchResult,
    SubmissionFormat,
    direct_acquisition,
    is_stub_document_path,
)
from edgar_sec.domain.document.models import (
    DocumentLocator,
    derive_document_locator_key,
)
from edgar_sec.domain.document.route import archive_root_candidate
from edgar_sec.domain.sec_urls import (
    SEC_ARCHIVE_BASE,
    full_submission_url_for,
    normalize_accession,
    parse_archive_url,
)
from edgar_sec.engine.document.unpacking.unpacker import (
    extract_target_sub_document_selection,
    has_sgml_documents,
    strip_pem_envelope,
)

log = logging.getLogger("document_storage.fetcher")


@dataclass(frozen=True, slots=True)
class EnvelopeExtraction:
    """What one response scan produced for a requested locator.

    ``submission`` is set only when the response was an SGML envelope, and then names
    every sub-document it described alongside the one selected body.
    """

    payload: bytes | None = None
    bundle: bytes | None = None
    submission: AcquiredSubmission | None = None


@runtime_checkable
class ArchiveFetcher(Protocol):
    """Fetch one archive document without deciding how it is persisted."""

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        """Acquire the bytes identified by ``locator``."""

    def fetch_bundle(self, locator: DocumentLocator) -> BundleFetchResult:
        """Acquire the complete submission bundle for ``locator``.

        The bundle is returned raw (a ``BundleFetchResult``); it is the caller's
        responsibility to scan it for a primary and any delegated exhibits.
        """


def extract_from_sgml_envelope(
    raw_payload: bytes,
    locator: DocumentLocator,
    *,
    source: AcquisitionSource | None = None,
) -> EnvelopeExtraction:
    """Select the target sub-document when the payload is an SGML envelope.

    Scans the whole payload, never a prefix: PEM headers push the first block past one.
    """
    if not raw_payload:
        return EnvelopeExtraction()
    payload = strip_pem_envelope(raw_payload)
    if not has_sgml_documents(payload):
        return EnvelopeExtraction(
            payload=payload,
            submission=direct_acquisition(locator, payload, source=source),
        )

    form_value = locator.form.strip().upper() if locator.form else None
    targets: tuple[str, ...] = ()
    if form_value:
        targets = (
            (form_value, f"{form_value}/A", form_value[:-2])
            if form_value.endswith("/A")
            else (form_value, f"{form_value}/A")
        )
    selection = extract_target_sub_document_selection(
        payload,
        target_types=targets,
        primary_filename=locator.document_path,
        fallback_to_sequence_one=True,
    )
    if selection is None:
        return EnvelopeExtraction(bundle=payload)
    return EnvelopeExtraction(
        payload=selection.payload,
        bundle=payload,
        submission=AcquiredSubmission(
            requested_locator=locator,
            source_format=SubmissionFormat.SGML,
            documents=selection.documents,
            selected_index=selection.selected_index,
            selected_payload=selection.payload,
            source=source,
        ),
    )


def _ok(locator: DocumentLocator, extraction: EnvelopeExtraction) -> FetchResult:
    acquired = extraction.submission
    if acquired is None:
        raise ValueError("a successful extraction must carry an acquired submission")
    return FetchResult(
        locator=locator,
        status="ok",
        acquired=acquired,
        source_payload=extraction.bundle,
    )


def _archive_source(url: str | None) -> AcquisitionSource:
    return AcquisitionSource(
        kind=AcquisitionSourceKind.ARCHIVE_URL, reference=url or ""
    )


def _fixture_source(key: str) -> AcquisitionSource:
    return AcquisitionSource(kind=AcquisitionSourceKind.FIXTURE, reference=key)


def _submission_targets(locator: DocumentLocator) -> tuple[str | None, str | None]:
    """Return ``(direct_url, full_submission_url)`` for a locator."""
    parts = parse_archive_url(locator.archive_url)
    full_sub_url = (
        full_submission_url_for(parts.archive_cik, locator.accession) if parts else None
    )
    return locator.archive_url, full_sub_url


def archive_root_url(locator: DocumentLocator) -> str | None:
    """Return the archive-root URL for a rendered locator's original document.

    ``None`` for a non-rendered path. Identity is untouched: only the URL changes.
    """
    basename = archive_root_candidate(locator.document_path)
    if basename is None or not locator.archive_url:
        return None
    parts = parse_archive_url(locator.archive_url)
    if parts is None:
        return None
    return f"{SEC_ARCHIVE_BASE}/{parts.archive_cik}/{parts.accession}/{basename}"


def _acquisition_urls(
    locator: DocumentLocator,
) -> tuple[str | None, str | None, str | None]:
    """Return ``(preferred, fallback_rendered, full_submission)`` acquisition URLs.

    The rendering is retained as fallback so a root document that does not exist
    cannot turn a reachable filing into a failure.
    """
    direct_url, full_sub_url = _submission_targets(locator)
    root_url = archive_root_url(locator)
    if root_url is None:
        return direct_url, None, full_sub_url
    return root_url, direct_url, full_sub_url


def _lookup_paths(locator: DocumentLocator) -> tuple[str, ...]:
    """Return fixture lookup keys in preference order for one locator.

    A rendered path resolves to its archive-root basename first and keeps the
    rendered path as a fallback, mirroring the URL fetchers' candidate order.
    """
    basename = archive_root_candidate(locator.document_path)
    if basename is None:
        return (locator.document_path,)
    return (basename, locator.document_path)


class FixtureArchiveFetcher:
    """Read raw payloads from one or more fixture stores.

    Connections open per process, not in the constructor: a ``sqlite3`` connection
    cannot cross a pickle, so only paths travel to a pool child.
    """

    __slots__ = ("_db_paths", "_local")

    def __init__(self, db_paths: Iterable[str | Path]) -> None:
        self._db_paths = tuple(str(Path(p)) for p in db_paths)
        self._local = threading.local()

    def _stores(self) -> list[Any]:
        stores = getattr(self._local, "stores", None)
        if stores is None:
            from edgar_sec.pipelines.document_storage.fixture_store import FixtureStore

            stores = []
            for path in self._db_paths:
                if Path(path).is_file():
                    stores.append(FixtureStore(path, read_only=True))
            self._local.stores = stores
        return stores

    def __getstate__(self) -> dict[str, object]:
        # Only the paths travel: an open sqlite connection cannot be pickled.
        return {"_db_paths": self._db_paths}

    def __setstate__(self, state: dict[str, object]) -> None:
        self._db_paths = state["_db_paths"]  # type: ignore[assignment]
        # Connections belong to the process that opens them.
        self._local = threading.local()

    def _lookup(self, key: str) -> bytes | None:
        for store in self._stores():
            payload = store.get(key)
            if payload is not None:
                return payload
        return None

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        try:
            for candidate_path in _lookup_paths(locator):
                key = derive_document_locator_key(
                    str(locator.accession), candidate_path
                )
                payload = self._lookup(key)
                if payload is not None:
                    extraction = extract_from_sgml_envelope(
                        payload, locator, source=_fixture_source(candidate_path)
                    )
                    if extraction.payload is not None:
                        return _ok(locator, extraction)

            # Fall back to the full submission bundle, which the catalog may
            # have recorded under the accession rather than the sub-document.
            canonical = normalize_accession(locator.accession)
            if canonical:
                from edgar_sec.domain.sec_urls import accession_hyphenated

                bundle_name = f"{accession_hyphenated(canonical)}.txt"
                payload = self._lookup(
                    derive_document_locator_key(str(locator.accession), bundle_name)
                )
                if payload is not None:
                    extraction = extract_from_sgml_envelope(
                        payload, locator, source=_fixture_source(bundle_name)
                    )
                    if extraction.payload is not None:
                        return _ok(locator, extraction)
        except Exception as exc:  # noqa: BLE001 - fetch failures become statuses
            log.debug(
                "fixture fetch failed for %s: %s", locator.document_locator_key, exc
            )
            return FetchResult(locator=locator, status="failed", error=str(exc))
        return FetchResult(locator=locator, status="missing")

    def fetch_bundle(self, locator: DocumentLocator) -> BundleFetchResult:
        """Acquire the complete submission bundle for a candidate locator."""
        canonical = normalize_accession(locator.accession)
        if canonical is None:
            return BundleFetchResult(
                status="missing", error="accession could not be normalized"
            )
        from edgar_sec.domain.sec_urls import accession_hyphenated

        bundle_name = f"{accession_hyphenated(canonical)}.txt"
        key = derive_document_locator_key(str(locator.accession), bundle_name)
        payload = self._lookup(key)
        if payload is not None:
            return BundleFetchResult(
                status="ok", payload=payload, source=_fixture_source(bundle_name)
            )
        return BundleFetchResult(
            status="missing", error="bundle not found in fixture store"
        )

    def close(self) -> None:
        """Close any fixture connections this process opened."""
        stores = getattr(self._local, "stores", None)
        if stores is not None:
            for store in stores:
                with suppress(Exception):
                    store.close()
            self._local.stores = []


class BrokerArchiveFetcher:
    """Route archive fetches through the broker socket, behind an optional cache probe.

    The probe is strictly read-only — pacing and ledger stay broker-owned — so only
    cache misses traverse the socket.
    """

    __slots__ = ("_broker", "_cache", "_cache_dir")

    def __init__(self, broker_client: Any, cache_reader: Any | None = None) -> None:
        self._broker = broker_client
        self._cache = cache_reader
        self._cache_dir = getattr(cache_reader, "cache_dir", None)

    def __getstate__(self) -> dict[str, object]:
        return {
            "socket_path": getattr(self._broker, "socket_path", None),
            "cache_dir": self._cache_dir,
        }

    def __setstate__(self, state: dict[str, object]) -> None:
        from edgar_sec.infra.broker.sec_broker import SecBrokerClient

        socket_path = state.get("socket_path")
        self._broker = SecBrokerClient(socket_path) if socket_path is not None else None
        # A warm-cache reader is an open handle and cannot cross a process
        # boundary; the child reattaches to the cache through its own session.
        self._cache_dir = state.get("cache_dir")
        self._cache = None

    @property
    def metrics(self) -> Any:
        """Broker-side metrics, or None when the broker does not report them."""
        return getattr(self._broker, "metrics", None)

    def _payload_from(self, archive_url: str) -> tuple[bytes | None, str | None]:
        """Return ``(payload, error)`` for one URL, probing the warm cache first."""
        if self._cache is not None:
            with suppress(Exception):
                payload = self._cache.get(archive_url)
                if payload is not None:
                    return payload, None
        if self._broker is None:
            return None, "broker socket path was not configured"
        try:
            result = self._broker.fetch(archive_url)
        except Exception as exc:  # noqa: BLE001 - transport errors become statuses
            return None, str(exc) or type(exc).__name__
        if result.get("status") == "ok" and result.get("payload") is not None:
            return result["payload"], None
        return None, result.get("error") or "broker reported failure"

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        preferred, fallback_url, full_sub_url = _acquisition_urls(locator)
        is_stub = is_stub_document_path(locator.document_path)
        primary_error: str | None = None

        for candidate in (preferred, fallback_url):
            if candidate is None or is_stub:
                continue
            payload, error = self._payload_from(candidate)
            if payload is not None:
                extraction = extract_from_sgml_envelope(
                    payload, locator, source=_archive_source(candidate)
                )
                if extraction.payload is not None:
                    return _ok(locator, extraction)
            primary_error = primary_error or error

        if full_sub_url and full_sub_url != locator.archive_url:
            payload, error = self._payload_from(full_sub_url)
            if payload is not None:
                extraction = extract_from_sgml_envelope(
                    payload, locator, source=_archive_source(full_sub_url)
                )
                if extraction.payload is not None:
                    return _ok(locator, extraction)
                return FetchResult(
                    locator=locator,
                    status="failed",
                    error=f"sgml_subdocument_not_found (form={locator.form})",
                )
            return FetchResult(
                locator=locator,
                status="failed",
                error=primary_error or error or "fetch failed",
            )

        return FetchResult(
            locator=locator,
            status="failed",
            error=primary_error or "fetch failed",
        )

    def fetch_bundle(self, locator: DocumentLocator) -> BundleFetchResult:
        """Acquire the complete submission bundle for a candidate locator."""
        from edgar_sec.domain.sec_urls import parse_archive_url

        parts = parse_archive_url(locator.archive_url)
        if parts is None:
            return BundleFetchResult(
                status="missing", error="locator has no archive URL"
            )
        url = full_submission_url_for(parts.archive_cik, locator.accession)
        payload, error = self._payload_from(url)
        if payload is not None:
            return BundleFetchResult(
                status="ok", payload=payload, source=_archive_source(url)
            )
        if error is not None and "not found" in error.lower():
            return BundleFetchResult(status="missing", error=error)
        return BundleFetchResult(status="failed", error=error or "bundle fetch failed")


class LiveArchiveFetcher:
    """Acquire archive bytes through a caller-supplied HTTP client.

    Not the supported path under a process pool: the client's rate limiter must stay
    single-owner, which is what ``BrokerArchiveFetcher`` provides.
    """

    __slots__ = ("_http_client",)

    def __init__(self, http_client: Any) -> None:
        self._http_client = http_client

    def __getstate__(self) -> dict[str, object]:
        return {
            "user_agent": getattr(self._http_client, "user_agent", None),
            "cache_dir": getattr(self._http_client, "cache_dir", None),
        }

    def __setstate__(self, state: dict[str, object]) -> None:
        from edgar_sec.infra.sec_http.client import SecHttpClient

        self._http_client = SecHttpClient(
            user_agent=state.get("user_agent"),
            cache_dir=state.get("cache_dir"),
        )

    @property
    def metrics(self) -> Any:
        """Client-side HTTP metrics."""
        return getattr(self._http_client, "metrics", None)

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        preferred, fallback_url, full_sub_url = _acquisition_urls(locator)
        is_stub = is_stub_document_path(locator.document_path)
        primary_error: str | None = None

        for candidate in (preferred, fallback_url):
            if candidate is None or is_stub:
                continue
            try:
                payload = self._http_client.get_bytes(candidate)
                extraction = extract_from_sgml_envelope(
                    payload, locator, source=_archive_source(candidate)
                )
                if extraction.payload is not None:
                    return _ok(locator, extraction)
            except Exception as exc:  # noqa: BLE001 - falls back to the bundle
                primary_error = primary_error or str(exc)

        if full_sub_url and full_sub_url != locator.archive_url:
            try:
                payload = self._http_client.get_bytes(full_sub_url)
                extraction = extract_from_sgml_envelope(
                    payload, locator, source=_archive_source(full_sub_url)
                )
                if extraction.payload is not None:
                    return _ok(locator, extraction)
                return FetchResult(
                    locator=locator,
                    status="failed",
                    error=f"sgml_subdocument_not_found (form={locator.form})",
                )
            except Exception as exc:  # noqa: BLE001
                return FetchResult(
                    locator=locator,
                    status="failed",
                    error=primary_error or str(exc),
                )

        return FetchResult(
            locator=locator,
            status="failed",
            error=primary_error or "fetch failed",
        )

    def fetch_bundle(self, locator: DocumentLocator) -> BundleFetchResult:
        """Acquire the complete submission bundle for a candidate locator."""
        from edgar_sec.domain.sec_urls import parse_archive_url

        parts = parse_archive_url(locator.archive_url)
        if parts is None:
            return BundleFetchResult(
                status="missing", error="locator has no archive URL"
            )
        url = full_submission_url_for(parts.archive_cik, locator.accession)
        try:
            payload = self._http_client.get_bytes(url)
        except Exception as exc:  # noqa: BLE001 - transport errors become statuses
            if "404" in str(exc) or "404" in (getattr(exc, "url", "") or ""):
                return BundleFetchResult(status="missing", error=str(exc))
            return BundleFetchResult(status="failed", error=str(exc))
        if payload:
            return BundleFetchResult(
                status="ok", payload=payload, source=_archive_source(url)
            )
        return BundleFetchResult(status="missing", error="bundle returned empty")


def build_broker_fetcher(
    broker_socket: str | Path, cache_reader: Any | None = None
) -> BrokerArchiveFetcher:
    """Build a broker-backed fetcher with an optional read-only cache probe.

    Nothing fabricates a cache reader from a directory: a probe that silently opened a
    writable cache would move pacing and ledger ownership out of the broker.
    """
    from edgar_sec.infra.broker.sec_broker import SecBrokerClient

    return BrokerArchiveFetcher(
        SecBrokerClient(broker_socket), cache_reader=cache_reader
    )


def make_archive_fetcher(
    mode: str,
    *,
    db_paths: Sequence[str | Path] | None = None,
    http_client: Any | None = None,
    broker_socket: str | Path | None = None,
    cache_reader: Any | None = None,
) -> ArchiveFetcher:
    """Construct the configured offline, broker, or live fetcher."""
    normalized = mode.strip().lower()
    if normalized == "fixture":
        if not db_paths:
            raise ValueError("fixture mode requires db_paths")
        return FixtureArchiveFetcher(db_paths)
    if normalized in ("live", "production", "broker"):
        if broker_socket is not None:
            return build_broker_fetcher(broker_socket, cache_reader)
        if http_client is None:
            raise ValueError("live mode requires http_client")
        return LiveArchiveFetcher(http_client)
    raise ValueError(f"unsupported archive fetcher mode: {mode!r}")


__all__ = [
    "ArchiveFetcher",
    "BrokerArchiveFetcher",
    "EnvelopeExtraction",
    "FixtureArchiveFetcher",
    "LiveArchiveFetcher",
    "build_broker_fetcher",
    "extract_from_sgml_envelope",
    "make_archive_fetcher",
]
