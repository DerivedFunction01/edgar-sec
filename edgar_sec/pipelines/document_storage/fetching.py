"""The archive fetcher seam: acquire document bytes, decide nothing about storage.

Three backends implement one protocol:

``FixtureArchiveFetcher``
    Offline. Reads content-addressed raw payloads from a fixture store. Its own
    connections are per-process, which is what makes it safe to hand to a
    process pool: a ``sqlite3`` connection cannot cross a process boundary, so
    the fetcher serializes only its *paths* and opens connections after the
    child starts.
``BrokerArchiveFetcher``
    Routes through the broker socket, with an optional read-only warm-cache
    probe in front. Only cache misses traverse the socket.
``LiveArchiveFetcher``
    Direct HTTP, used in-process. Under a process pool the broker is the
    supported path, because a live client owns a rate limiter that must stay
    single-owner.

A fetcher reports what happened; it never writes a checkpoint, never opens a
transaction, and never decides that a payload is good enough. Keeping that
boundary sharp is what lets the same fetcher serve a worker, a fixture builder,
and the review tool.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from edgar_sec.domain.document.acquisition import (
    FetchResult,
    is_stub_document_path,
)
from edgar_sec.domain.document.models import (
    DocumentLocator,
    derive_document_locator_key,
)
from edgar_sec.domain.sec_urls import (
    full_submission_url_for,
    normalize_accession,
    parse_archive_url,
)
from edgar_sec.engine.document.unpacking.unpacker import (
    extract_target_sub_document,
    has_sgml_documents,
    strip_pem_envelope,
)

log = logging.getLogger("document_storage.fetcher")


@runtime_checkable
class ArchiveFetcher(Protocol):
    """Fetch one archive document without deciding how it is persisted."""

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        """Acquire the bytes identified by ``locator``."""


def extract_from_sgml_envelope(
    raw_payload: bytes, locator: DocumentLocator
) -> tuple[bytes | None, bytes | None]:
    """Select the target sub-document when the payload is an SGML envelope.

    Returns ``(payload, source_bundle)``. ``payload`` is the selected
    sub-document's text bytes, or the unchanged payload when the input is not an
    envelope. ``source_bundle`` carries the PEM-stripped bundle when a selection
    happened, so an exhibit second pass can resolve in-bundle exhibits without a
    refetch; it is None otherwise.

    PEM-wrapped payloads are unwrapped first, then the *whole* payload is scanned
    for ``<DOCUMENT>`` blocks — never a fixed-size prefix, because PEM transport
    headers push the first block past the start of the file.
    """
    if not raw_payload:
        return None, None
    payload = strip_pem_envelope(raw_payload)
    if not has_sgml_documents(payload):
        return payload, None

    form_value = locator.form.strip().upper() if locator.form else None
    targets: tuple[str, ...] = ()
    if form_value:
        targets = (
            (form_value, f"{form_value}/A", form_value[:-2])
            if form_value.endswith("/A")
            else (form_value, f"{form_value}/A")
        )
    selected = extract_target_sub_document(
        payload,
        target_types=targets,
        primary_filename=locator.document_path,
        fallback_to_sequence_one=True,
    )
    return selected, payload


def _ok(locator: DocumentLocator, payload: bytes, source: bytes | None) -> FetchResult:
    return FetchResult(
        locator=locator, payload=payload, status="ok", source_payload=source
    )


def _submission_targets(locator: DocumentLocator) -> tuple[str | None, str | None]:
    """Return ``(direct_url, full_submission_url)`` for a locator."""
    parts = parse_archive_url(locator.archive_url)
    full_sub_url = (
        full_submission_url_for(parts.archive_cik, locator.accession) if parts else None
    )
    return locator.archive_url, full_sub_url


# --------------------------------------------------------------------------
# Offline
# --------------------------------------------------------------------------


class FixtureArchiveFetcher:
    """Read raw payloads from one or more fixture stores.

    Connections are opened lazily per process rather than in the constructor.
    That is not an optimization: the fetcher is shipped to a process pool, and a
    ``sqlite3`` connection bound to the parent process's file descriptors is
    unusable in the child. Serializing paths and opening on first use is what
    makes the same object valid on both sides of a pickle.
    """

    __slots__ = ("_db_paths", "_local")

    def __init__(self, db_paths: Iterable[str | Path]) -> None:
        self._db_paths = tuple(str(Path(p)) for p in db_paths)
        self._local = threading.local()

    def _stores(self) -> list[Any]:
        stores = getattr(self._local, "stores", None)
        if stores is None:
            from edgar_sec.infra.storage.fixture_store import FixtureStore

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
            payload = self._lookup(locator.document_locator_key)
            if payload is not None:
                extracted, source = extract_from_sgml_envelope(payload, locator)
                if extracted is not None:
                    return _ok(locator, extracted, source)

            # Fall back to the full submission bundle, which the catalog may
            # have recorded under the accession rather than the sub-document.
            canonical = normalize_accession(locator.accession)
            if canonical:
                from edgar_sec.domain.sec_urls import accession_hyphenated

                bundle_key = derive_document_locator_key(
                    str(locator.accession), f"{accession_hyphenated(canonical)}.txt"
                )
                payload = self._lookup(bundle_key)
                if payload is not None:
                    extracted, source = extract_from_sgml_envelope(payload, locator)
                    if extracted is not None:
                        return _ok(locator, extracted, source)
        except Exception as exc:  # noqa: BLE001 - fetch failures become statuses
            log.debug(
                "fixture fetch failed for %s: %s", locator.document_locator_key, exc
            )
            return FetchResult(
                locator=locator, payload=None, status="failed", error=str(exc)
            )
        return FetchResult(locator=locator, payload=None, status="missing")

    def close(self) -> None:
        """Close any fixture connections this process opened."""
        stores = getattr(self._local, "stores", None)
        if stores is not None:
            for store in stores:
                with suppress(Exception):
                    store.close()
            self._local.stores = []


# --------------------------------------------------------------------------
# Broker
# --------------------------------------------------------------------------


class BrokerArchiveFetcher:
    """Route archive fetches through the broker socket.

    When ``cache_reader`` is supplied, each URL is probed against the local warm
    HTTP cache before the RPC. A cache hit is byte-identical to the broker's
    response — cache entries never expire and successful fetches clear their
    failure-ledger entry — so only misses traverse the socket. The reader is
    strictly read-only: cache writes, ledger updates, pacing, and retries stay
    broker-owned.
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
        _direct, full_sub_url = _submission_targets(locator)
        is_stub = is_stub_document_path(locator.document_path)
        primary_error: str | None = None

        if not is_stub:
            payload, error = self._payload_from(locator.archive_url)
            if payload is not None:
                extracted, source = extract_from_sgml_envelope(payload, locator)
                if extracted is not None:
                    return _ok(locator, extracted, source)
            primary_error = error

        if full_sub_url and full_sub_url != locator.archive_url:
            payload, error = self._payload_from(full_sub_url)
            if payload is not None:
                extracted, source = extract_from_sgml_envelope(payload, locator)
                if extracted is not None:
                    return _ok(locator, extracted, source)
                return FetchResult(
                    locator=locator,
                    payload=None,
                    status="failed",
                    error=f"sgml_subdocument_not_found (form={locator.form})",
                )
            return FetchResult(
                locator=locator,
                payload=None,
                status="failed",
                error=primary_error or error or "fetch failed",
            )

        return FetchResult(
            locator=locator,
            payload=None,
            status="failed",
            error=primary_error or "fetch failed",
        )


# --------------------------------------------------------------------------
# Direct HTTP
# --------------------------------------------------------------------------


class LiveArchiveFetcher:
    """Acquire archive bytes through a caller-supplied HTTP client.

    The client is injected rather than constructed so tests can supply a fake at
    the transport seam, and so a run can share one client's rate limiter across
    threads. Under a process pool this is not the supported path: prefer
    :class:`BrokerArchiveFetcher`, whose pacing stays single-owner.
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
        from edgar_sec.infra.sec_http import make_sec_http_client

        self._http_client = make_sec_http_client(
            user_agent=state.get("user_agent"),
            cache_dir=state.get("cache_dir"),
        )

    @property
    def metrics(self) -> Any:
        """Client-side HTTP metrics."""
        return getattr(self._http_client, "metrics", None)

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        _direct, full_sub_url = _submission_targets(locator)
        is_stub = is_stub_document_path(locator.document_path)
        primary_error: str | None = None

        if not is_stub:
            try:
                payload = self._http_client.get_bytes(locator.archive_url)
                extracted, source = extract_from_sgml_envelope(payload, locator)
                if extracted is not None:
                    return _ok(locator, extracted, source)
            except Exception as exc:  # noqa: BLE001 - falls back to the bundle
                primary_error = str(exc)

        if full_sub_url and full_sub_url != locator.archive_url:
            try:
                payload = self._http_client.get_bytes(full_sub_url)
                extracted, source = extract_from_sgml_envelope(payload, locator)
                if extracted is not None:
                    return _ok(locator, extracted, source)
                return FetchResult(
                    locator=locator,
                    payload=None,
                    status="failed",
                    error=f"sgml_subdocument_not_found (form={locator.form})",
                )
            except Exception as exc:  # noqa: BLE001
                return FetchResult(
                    locator=locator,
                    payload=None,
                    status="failed",
                    error=primary_error or str(exc),
                )

        return FetchResult(
            locator=locator,
            payload=None,
            status="failed",
            error=primary_error or "fetch failed",
        )


def build_broker_fetcher(
    broker_socket: str | Path, cache_reader: Any | None = None
) -> BrokerArchiveFetcher:
    """Build a broker-backed fetcher with an optional read-only cache probe.

    ``cache_reader`` is duck-typed: anything with ``get(url)`` and
    ``cache_dir`` works, which is what keeps the warm-cache probe testable at
    the transport seam. v2 has no read-only cache reader yet, so this does not
    fabricate one from a directory — a probe that silently opened a *writable*
    cache would move pacing and ledger ownership out of the broker.
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
    """Construct the configured offline, broker, or live fetcher.

    On the broker path ``cache_reader`` adds a read-only warm-cache probe in
    front of the broker RPC; only cache misses traverse the socket. It has no
    effect on the live path, whose client already owns its cache.
    """
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
    "FixtureArchiveFetcher",
    "LiveArchiveFetcher",
    "build_broker_fetcher",
    "extract_from_sgml_envelope",
    "make_archive_fetcher",
]
