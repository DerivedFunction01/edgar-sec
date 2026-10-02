"""Fixture discovery and raw-payload fill operations for Phase 2.5."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.domain.document.models import DocumentLocator, RawDocumentBlob
from edgar_sec.foundation.hashing import sha256_bytes, sha256_text
from edgar_sec.foundation.runtime.paths import ProjectPaths
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.fixture_store import FixtureStore, FixtureStoreError
from edgar_sec.pipelines.document_storage.fetching import LiveArchiveFetcher

MANIFEST_SCHEMA_VERSION = 2
_FIXTURE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_WRITE_BATCH_SIZE = 128

#: Extension to MIME, matching v1's fixture vocabulary so a fixture filled here
#: and one filled by v1 describe the same document identically.
_MIME_BY_SUFFIX = {
    ".htm": "text/html",
    ".html": "text/html",
    ".xhtml": "text/html",
    ".txt": "text/plain",
    ".xml": "text/xml",
}
_DEFAULT_MIME = "application/octet-stream"


def mime_type_for(document_path: str) -> str:
    """Infer a document's MIME type from its extension."""
    suffix = Path(document_path.strip().lower()).suffix
    return _MIME_BY_SUFFIX.get(suffix, _DEFAULT_MIME)


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


def validate_fixture_id(fixture_id: str) -> str:
    """Reject fixture IDs that could escape the configured fixture root."""
    if not _FIXTURE_ID.fullmatch(fixture_id) or fixture_id in {".", ".."}:
        raise FixtureOperatorError(f"invalid fixture id: {fixture_id!r}")
    return fixture_id


def list_fixtures(paths: ProjectPaths) -> tuple[FixtureInfo, ...]:
    """Discover fixtures newest-first and report database/manifest health."""
    root = paths.fixtures_root
    if not root.is_dir():
        return ()
    found: list[tuple[float, FixtureInfo]] = []
    for directory in root.iterdir():
        if not directory.is_dir() or not (directory / "fixture.sqlite").is_file():
            continue
        fixture_id = directory.name
        db_path = paths.fixture_db_path(fixture_id)
        count: int | None = None
        try:
            with FixtureStore(db_path, read_only=True) as store:
                count = store.count()
        except FixtureStoreError:
            pass
        manifest_path = paths.fixture_manifest_path(fixture_id)
        status = "missing"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if (
                    not isinstance(manifest, dict)
                    or manifest.get("fixture_id") != fixture_id
                ):
                    status = "invalid"
                elif manifest.get("manifest_schema_version") == MANIFEST_SCHEMA_VERSION:
                    status = "valid"
                else:
                    status = "legacy"
            except (OSError, json.JSONDecodeError):
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
        json_ttl_s=settings.json_ttl_s,
    )


def _document_blob(locator: DocumentLocator, raw_payload: bytes) -> RawDocumentBlob:
    """Describe one fetched payload in the fixture's ``document_blobs`` shape."""
    return RawDocumentBlob(
        doc_id=locator.document_locator_key,
        accession=str(locator.accession),
        document_path=locator.document_path,
        byte_size=len(raw_payload),
        mime_type=mime_type_for(locator.document_path),
        raw_payload_sha256=sha256_bytes(raw_payload),
    )


def _backfill_document_metadata(
    store: FixtureStore,
    locators: Sequence[DocumentLocator],
    failures: list[dict[str, str]],
) -> int:
    """Re-derive metadata rows for payloads recorded before the table existed.

    A payload is a one-way digest, so the accession, path, MIME and source hash
    of a document fetched by an older fill cannot be recovered from the payload
    table alone -- the bytes have to be read back. That costs local I/O, so it
    runs only for documents that have a payload but no metadata row, which makes
    it self-limiting: a fully-recorded fixture pays nothing on a later fill.

    The alternative, refusing a fill until the operator migrated the fixture
    separately, would have made the common case (extend a fixture) fail for a
    reason with no user-visible cause.
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
    paths: ProjectPaths,
    fixture_id: str,
    locators: Sequence[DocumentLocator],
    limit: int | None = None,
    workers: int | None = None,
    http_client: Any | None = None,
    target_reference: str | None = None,
) -> FixtureFillReport:
    """Fetch missing raw payloads with shared HTTP pacing and one SQLite writer."""
    fixture_id = validate_fixture_id(fixture_id)
    unique: list[DocumentLocator] = []
    seen: set[str] = set()
    for locator in locators:
        if locator.document_locator_key not in seen:
            seen.add(locator.document_locator_key)
            unique.append(locator)
    if limit is not None and limit > 0:
        unique = unique[:limit]

    worker_count = derive_resources().threads if workers is None else workers
    if worker_count < 1:
        raise FixtureOperatorError("workers must be positive")

    database = paths.fixture_db_path(fixture_id)
    manifest_path = paths.fixture_manifest_path(fixture_id)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    fingerprint = sha256_text(
        canonical_json([locator.document_locator_key for locator in unique])
    )
    client = http_client if http_client is not None else _make_http_client()
    fetcher = LiveArchiveFetcher(client)
    failures: list[dict[str, str]] = []
    staged: list[tuple[str, bytes]] = []
    staged_meta: list[RawDocumentBlob] = []
    staged_forms: dict[str, str] = {}
    already_present = 0
    newly_written = 0

    try:
        with FixtureStore(database) as store:
            pending: list[DocumentLocator] = []
            to_backfill: list[DocumentLocator] = []
            for locator in unique:
                key = locator.document_locator_key
                if store.has(key):
                    already_present += 1
                    if not store.has_document(key):
                        to_backfill.append(locator)
                else:
                    pending.append(locator)
            backfilled = _backfill_document_metadata(store, to_backfill, failures)

            def fetch(locator: DocumentLocator) -> tuple[DocumentLocator, Any]:
                return locator, fetcher.fetch(locator)

            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                iterator = iter(pending)
                active: dict[Future[tuple[DocumentLocator, Any]], DocumentLocator] = {}
                for _ in range(min(worker_count, len(pending))):
                    locator = next(iterator)
                    active[pool.submit(fetch, locator)] = locator

                while active:
                    completed, _ = wait(active, return_when=FIRST_COMPLETED)
                    for future in completed:
                        locator = active.pop(future)
                        try:
                            _locator, result = future.result()
                            if result.ok and result.payload is not None:
                                raw_payload = result.source_payload or result.payload
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
                            newly_written += store.put_many(staged)
                            staged.clear()
                            store.put_documents(staged_meta, staged_forms)
                            staged_meta.clear()
                            staged_forms.clear()
                        try:
                            next_locator = next(iterator)
                        except StopIteration:
                            continue
                        active[pool.submit(fetch, next_locator)] = next_locator
            if staged:
                newly_written += store.put_many(staged)
                staged.clear()
            store.put_documents(staged_meta, staged_forms)
            staged_meta.clear()
            staged_forms.clear()
            payload_count = store.count()

        prior: dict[str, Any] = {}
        if manifest_path.is_file():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if (
                    isinstance(loaded, dict)
                    and loaded.get("fixture_id") == fixture_id
                    and loaded.get("manifest_schema_version") == MANIFEST_SCHEMA_VERSION
                ):
                    prior = loaded
            except (OSError, json.JSONDecodeError) as exc:
                raise FixtureOperatorError(
                    f"invalid fixture manifest: {manifest_path}"
                ) from exc

        summary = {
            "target_fingerprint": fingerprint,
            "target_reference": Path(target_reference).name
            if target_reference
            else None,
            "requested": len(unique),
            "already_present": already_present,
            "newly_written": newly_written,
            "failed": len(failures),
            "completed_at": now,
        }
        manifest = {
            "manifest_kind": "raw_payload_fixture",
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "fixture_id": fixture_id,
            "storage_format": "sqlite",
            "database_path": "fixture.sqlite",
            "created_at": prior.get("created_at", now),
            "updated_at": now,
            "payload_count": payload_count,
            "last_fill": summary,
        }
        atomic_write_json(manifest_path, manifest)
    except FixtureStoreError as exc:
        raise FixtureOperatorError(str(exc)) from exc

    return FixtureFillReport(
        fixture_id=fixture_id,
        requested=len(unique),
        already_present=already_present,
        newly_written=newly_written,
        failed=len(failures),
        failures=tuple(failures),
        target_fingerprint=fingerprint,
        backfilled_metadata=backfilled,
    )


__all__ = [
    "FixtureFillReport",
    "FixtureInfo",
    "FixtureOperatorError",
    "fill_fixture",
    "list_fixtures",
    "validate_fixture_id",
]
