"""Fixture discovery and raw-payload fill operations."""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.domain.document.models import DocumentLocator, RawDocumentBlob
from edgar_sec.domain.document.route import mime_type_for_suffix
from edgar_sec.foundation.hashing import sha256_bytes, sha256_text
from edgar_sec.foundation.runtime.fixtures import (
    FixtureManifestEnvelope,
    validate_fixture_component,
)
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_storage.fetching import LiveArchiveFetcher
from edgar_sec.pipelines.document_storage.fixture_store import (
    FixtureStore,
    FixtureStoreError,
)
from edgar_sec.pipelines.document_storage.paths import DocumentStoragePaths

_WRITE_BATCH_SIZE = 128

#: Extension to MIME is owned by ``domain.document.route`` so the fixture index and
#: the processor describe one document with the same type.


class FixtureOperatorError(RuntimeError):
    """A fixture could not be listed, filled, or selected for replay."""


@dataclass(frozen=True, slots=True)
class FixtureInfo:
    fixture_id: str
    payload_count: int | None
    manifest_status: str
    database_path: Path


@dataclass(frozen=True, slots=True)
class FixtureFillReport:
    fixture_id: str
    requested: int
    already_present: int
    newly_written: int
    failed: int
    failures: tuple[dict[str, str], ...]
    target_fingerprint: str
    backfilled_metadata: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "requested": self.requested,
            "already_present": self.already_present,
            "newly_written": self.newly_written,
            "metadata_backfilled": self.backfilled_metadata,
            "failed": self.failed,
            "failures": list(self.failures),
            "target_fingerprint": self.target_fingerprint,
        }


def list_fixtures(paths: DocumentStoragePaths) -> tuple[FixtureInfo, ...]:
    """Discover fixtures newest-first and report database/manifest health."""
    root = paths.fixtures_root
    if not root.is_dir():
        return ()
    found: list[tuple[float, FixtureInfo]] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        fixture_id = directory.name
        try:
            fixture = paths.fixture_paths(fixture_id)
        except ValueError:
            continue
        db_path = fixture.storage_path
        if not db_path.is_file():
            continue
        count: int | None = None
        try:
            with FixtureStore(db_path, read_only=True) as store:
                count = store.count()
        except FixtureStoreError:
            pass
        status = "missing"
        if fixture.manifest_path.is_file():
            try:
                raw = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
                manifest = FixtureManifestEnvelope.from_mapping(raw)
                status = (
                    "valid"
                    if manifest.fixture_kind == "document_storage.raw_payload"
                    and manifest.fixture_id == fixture_id
                    and manifest.storage_format == "sqlite"
                    and manifest.storage_path == fixture.storage_filename
                    else "invalid"
                )
            except (OSError, json.JSONDecodeError, ValueError):
                status = "invalid"
        updated = directory.stat().st_mtime
        found.append((updated, FixtureInfo(fixture_id, count, status, db_path)))
    return tuple(
        item for _, item in sorted(found, key=lambda row: (-row[0], row[1].fixture_id))
    )


def _make_http_client() -> Any:
    from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
    from edgar_sec.infra.sec_http.client import SecHttpClient

    settings = resolve_runtime_settings()
    return SecHttpClient.from_settings(
        settings.sec,
        cache_dir=settings.cache_root,
        ttl_s=settings.ttl_s,
    )


def _document_blob(locator: DocumentLocator, raw_payload: bytes) -> RawDocumentBlob:
    """Describe one fetched payload in the fixture's ``document_blobs`` shape."""
    return RawDocumentBlob(
        doc_id=locator.document_locator_key,
        accession=str(locator.accession),
        document_path=locator.document_path,
        byte_size=len(raw_payload),
        mime_type=mime_type_for_suffix(locator.document_path),
        raw_payload_sha256=sha256_bytes(raw_payload),
    )


def _backfill_document_metadata(
    store: FixtureStore,
    locators: Sequence[DocumentLocator],
    failures: list[dict[str, str]],
) -> int:
    """Re-derive metadata rows for payloads recorded before the table existed.

    A payload key is a one-way digest, so identity must be read back from the bytes.
    Runs only where a payload exists without a row, so a recorded fixture pays nothing.
    """
    if not locators:
        return 0
    recovered: list[RawDocumentBlob] = []
    forms: dict[str, str] = {}
    for locator in locators:
        key = locator.document_locator_key
        try:
            payload = store.get(key)
        except FixtureStoreError as exc:
            failures.append({"doc_id": key, "error": str(exc)})
            continue
        if payload is None:
            failures.append(
                {
                    "doc_id": key,
                    "error": "payload present in index but not stored",
                }
            )
            continue
        recovered.append(_document_blob(locator, payload))
        if locator.form:
            forms[key] = locator.form
    if recovered:
        store.put_documents(recovered, forms)
    return len(recovered)


def fill_fixture(
    *,
    paths: DocumentStoragePaths,
    fixture_id: str,
    locators: Sequence[DocumentLocator] | None = None,
    locator_source: Iterable[DocumentLocator] | None = None,
    limit: int | None = None,
    workers: int | None = None,
    http_client: Any | None = None,
    target_reference: str | None = None,
    target_fingerprint: str | None = None,
) -> FixtureFillReport:
    """Fetch missing raw payloads with shared HTTP pacing and one SQLite writer.

    ``locator_source`` is read lazily with at most ``workers`` fetches in flight; a
    caller holding the selection's identity passes ``target_fingerprint``.
    """
    try:
        fixture_id = validate_fixture_component(fixture_id, "fixture_id")
    except ValueError as exc:
        raise FixtureOperatorError(str(exc)) from exc
    source: Iterable[DocumentLocator] = (
        locator_source if locator_source is not None else (locators or ())
    )
    if limit is not None and limit > 0:
        source = itertools.islice(source, limit)

    worker_count = derive_resources().threads if workers is None else workers
    if worker_count < 1:
        raise FixtureOperatorError("workers must be positive")

    database = paths.fixture_db_path(fixture_id)
    manifest_path = paths.fixture_manifest_path(fixture_id)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    client = http_client if http_client is not None else _make_http_client()
    fetcher = LiveArchiveFetcher(client)
    failures: list[dict[str, str]] = []
    staged: list[tuple[str, bytes]] = []
    staged_meta: list[RawDocumentBlob] = []
    staged_forms: dict[str, str] = {}
    already_present = 0
    newly_written = 0
    requested = 0
    seen: set[str] = set()
    keys: list[str] = []
    backfilled = 0

    def flush_staged(store: FixtureStore) -> None:
        nonlocal newly_written
        if staged:
            newly_written += store.put_many(staged)
            staged.clear()
        store.put_documents(staged_meta, staged_forms)
        staged_meta.clear()
        staged_forms.clear()

    try:
        with FixtureStore(database) as store:
            to_backfill: list[DocumentLocator] = []

            def fetch(locator: DocumentLocator) -> tuple[DocumentLocator, Any]:
                return locator, fetcher.fetch(locator)

            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                active: dict[Future[tuple[DocumentLocator, Any]], DocumentLocator] = {}

                def drain() -> None:
                    nonlocal backfilled
                    completed, _ = wait(active, return_when=FIRST_COMPLETED)
                    for future in completed:
                        locator = active.pop(future)
                        try:
                            _locator, result = future.result()
                            if result.ok and result.acquired is not None:
                                acquired = result.acquired
                                raw_payload = (
                                    result.source_payload or acquired.selected_payload
                                )
                                staged.append(
                                    (locator.document_locator_key, raw_payload)
                                )
                                staged_meta.append(_document_blob(locator, raw_payload))
                                if locator.form:
                                    staged_forms[locator.document_locator_key] = (
                                        locator.form
                                    )
                            else:
                                failures.append(
                                    {
                                        "doc_id": locator.document_locator_key,
                                        "error": result.error or result.status,
                                    }
                                )
                        except Exception as exc:  # noqa: BLE001 - isolate one failed fetch
                            failures.append(
                                {
                                    "doc_id": locator.document_locator_key,
                                    "error": str(exc),
                                }
                            )
                        if len(staged) >= _WRITE_BATCH_SIZE:
                            flush_staged(store)
                    if len(to_backfill) >= _WRITE_BATCH_SIZE:
                        backfilled += _backfill_document_metadata(
                            store, to_backfill, failures
                        )
                        to_backfill.clear()

                for locator in source:
                    key = locator.document_locator_key
                    if key in seen:
                        continue
                    seen.add(key)
                    if target_fingerprint is None:
                        keys.append(key)
                    requested += 1
                    if store.has(key):
                        already_present += 1
                        if not store.has_document(key):
                            to_backfill.append(locator)
                        continue
                    active[pool.submit(fetch, locator)] = locator
                    while len(active) >= worker_count:
                        drain()

                while active:
                    drain()

            backfilled += _backfill_document_metadata(store, to_backfill, failures)
            to_backfill.clear()
            flush_staged(store)
            payload_count = store.count()

        fingerprint = target_fingerprint or sha256_text(canonical_json(keys))

        prior: FixtureManifestEnvelope | None = None
        if manifest_path.is_file():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                prior = FixtureManifestEnvelope.from_mapping(loaded)
                if (
                    prior.fixture_kind != "document_storage.raw_payload"
                    or prior.fixture_id != fixture_id
                    or prior.storage_format != "sqlite"
                    or prior.storage_path
                    != paths.fixture_paths(fixture_id).storage_filename
                ):
                    raise ValueError(
                        "fixture envelope identity or storage does not match"
                    )
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise FixtureOperatorError(
                    f"invalid fixture manifest: {manifest_path}"
                ) from exc

        summary = {
            "target_fingerprint": fingerprint,
            "target_reference": Path(target_reference).name
            if target_reference
            else None,
            "requested": requested,
            "already_present": already_present,
            "newly_written": newly_written,
            "failed": len(failures),
            "completed_at": now,
        }
        details = dict(prior.details) if prior is not None else {}
        details.update({"payload_count": payload_count, "last_fill": summary})
        manifest = FixtureManifestEnvelope(
            fixture_kind="document_storage.raw_payload",
            fixture_id=fixture_id,
            storage_format="sqlite",
            storage_path=paths.fixture_paths(fixture_id).storage_filename,
            created_at=prior.created_at if prior is not None else now,
            updated_at=now,
            details=details,
        )
        atomic_write_json(manifest_path, manifest.to_mapping())
    except FixtureStoreError as exc:
        raise FixtureOperatorError(str(exc)) from exc

    return FixtureFillReport(
        fixture_id=fixture_id,
        requested=requested,
        already_present=already_present,
        newly_written=newly_written,
        failed=len(failures),
        failures=tuple(failures),
        target_fingerprint=fingerprint,
        backfilled_metadata=backfilled,
    )


def verify_fixture_lineage(
    paths: DocumentStoragePaths,
    fixture_id: str,
    *,
    target_reference: str,
    target_fingerprint: str,
) -> None:
    """Refuse a fixture whose recorded last fill did not come from this selection.

    Only the most recent fill is recorded, so what a fixture may still hold after a
    selection changes belongs to a manifest-model change.
    """
    try:
        fixture_id = validate_fixture_component(fixture_id, "fixture_id")
    except ValueError as exc:
        raise FixtureOperatorError(str(exc)) from exc
    manifest_path = paths.fixture_manifest_path(fixture_id)
    if not manifest_path.is_file():
        raise FixtureOperatorError(f"fixture manifest not found: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureOperatorError(
            f"invalid fixture manifest: {manifest_path}"
        ) from exc
    try:
        envelope = FixtureManifestEnvelope.from_mapping(manifest)
    except ValueError as exc:
        raise FixtureOperatorError(
            f"invalid fixture manifest: {manifest_path}"
        ) from exc
    if (
        envelope.fixture_kind != "document_storage.raw_payload"
        or envelope.fixture_id != fixture_id
        or envelope.storage_format != "sqlite"
        or envelope.storage_path != paths.fixture_paths(fixture_id).storage_filename
    ):
        raise FixtureOperatorError(f"invalid fixture manifest: {manifest_path}")
    last_fill = envelope.details.get("last_fill")
    if not isinstance(last_fill, dict):
        raise FixtureOperatorError(f"fixture {fixture_id} records no last fill")
    recorded = (last_fill.get("target_reference"), last_fill.get("target_fingerprint"))
    if recorded != (target_reference, target_fingerprint):
        raise FixtureOperatorError(
            f"fixture {fixture_id} was last filled from {recorded[0]!r} "
            f"({recorded[1]!r}), not {target_reference!r} ({target_fingerprint!r}); "
            "refusing to replay a selection the fixture does not hold"
        )


__all__ = [
    "FixtureFillReport",
    "FixtureInfo",
    "FixtureOperatorError",
    "fill_fixture",
    "list_fixtures",
    "verify_fixture_lineage",
]
