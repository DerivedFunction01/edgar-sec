"""Create fixtures and append captured accession observations."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from itertools import groupby

from edgar_sec.domain.document_inventory.models import InventoryCohort
from edgar_sec.foundation.compression import compress_payload
from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.infra.broker.sec_broker import SecBroker
from edgar_sec.pipelines.document_inventory.fixture_store._db import (
    load_manifest,
    now_iso,
    open_writable,
    refresh_manifest,
    validate_database,
    write_manifest,
)
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    _CREATE_TABLES,
    FixtureContribution,
    FixtureManifestContribution,
    IndexCaptureFailure,
    IndexCaptureResult,
    IndexFixtureError,
    IndexFixtureManifest,
    SCHEMA_VERSION,
)
from edgar_sec.foundation.runtime.fixtures import FixturePaths


def create_index_fixture(
    paths: FixturePaths, *, fixture_id: str
) -> IndexFixtureManifest:
    if paths.manifest_path.exists() or paths.storage_path.exists():
        raise IndexFixtureError(f"fixture already exists: {paths.root}")
    connection = open_writable(paths.storage_path)
    try:
        for statement in _CREATE_TABLES:
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()
    manifest = IndexFixtureManifest(
        fixture_id=fixture_id,
        schema_version=SCHEMA_VERSION,
        capture_state="empty",
        contributions=(),
        page_count=0,
        accession_count=0,
        membership_count=0,
    )
    write_manifest(paths, manifest)
    return manifest


def _start_contribution(
    paths: FixturePaths,
    connection: sqlite3.Connection,
    contribution: FixtureContribution,
) -> tuple[FixtureManifestContribution, ...]:
    manifest = load_manifest(paths)
    if contribution.accession_count < 0:
        raise IndexFixtureError("contribution accession_count must be non-negative")
    contributions = list(manifest.contributions)
    existing_index = next(
        (
            i
            for i, item in enumerate(contributions)
            if item.request_fingerprint == contribution.request_fingerprint
        ),
        None,
    )
    current = FixtureManifestContribution(
        plan_id=contribution.plan_id,
        catalog_id=contribution.catalog_id,
        scope=contribution.scope,
        plan_schema_version=contribution.plan_schema_version,
        request_fingerprint=contribution.request_fingerprint,
        accession_count=contribution.accession_count,
        captured_accessions=0,
        failed_accessions=0,
        state="capturing",
        started_at=now_iso(),
        finished_at=None,
    )
    if existing_index is None:
        contributions.append(current)
    else:
        previous = contributions[existing_index]
        if (
            previous.plan_id != current.plan_id
            or previous.catalog_id != current.catalog_id
            or previous.accession_count != current.accession_count
        ):
            raise IndexFixtureError("request fingerprint describes conflicting input")
        contributions[existing_index] = current
    result = tuple(contributions)
    refresh_manifest(paths, connection, result)
    return result


def _record_member(
    connection: sqlite3.Connection,
    *,
    case_id: int | None,
    accession: str,
    source_cik: str,
    cohort_source_id: str,
    failure_code: str | None,
    raw_error: str | None,
    captured_at: str,
) -> bool:
    existed = (
        connection.execute(
            """
        SELECT 1 FROM cohort_members
        WHERE accession = ? AND source_cik = ? AND cohort_source_id = ?
        """,
            (accession, source_cik, cohort_source_id),
        ).fetchone()
        is not None
    )
    connection.execute(
        """
        INSERT INTO cohort_members
        (case_id, accession, source_cik, cohort_source_id, failure_code, raw_error, captured_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(accession, source_cik, cohort_source_id) DO UPDATE SET
            case_id = excluded.case_id,
            failure_code = excluded.failure_code,
            raw_error = excluded.raw_error,
            captured_at = excluded.captured_at
        """,
        (
            case_id,
            accession,
            source_cik,
            cohort_source_id,
            failure_code,
            raw_error,
            captured_at,
        ),
    )
    return not existed


def _cached_digest(
    connection: sqlite3.Connection, accession: str, request_url: str
) -> tuple[str, str] | None:
    row = connection.execute(
        """
        SELECT response_sha256, captured_at
        FROM index_cases JOIN index_responses USING (request_url, response_sha256)
        WHERE accession = ? AND request_url = ?
        ORDER BY captured_at DESC, response_sha256 DESC LIMIT 1
        """,
        (accession, request_url),
    ).fetchone()
    return (str(row[0]), str(row[1])) if row else None


def _case_id(
    connection: sqlite3.Connection,
    *,
    request_url: str,
    digest: str,
    accession: str,
    cohort_source_id: str,
) -> tuple[int, bool]:
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO index_cases
        (request_url, response_sha256, accession, cohort_source_id)
        VALUES (?, ?, ?, ?)
        """,
        (request_url, digest, accession, cohort_source_id),
    )
    if cursor.rowcount:
        return int(cursor.lastrowid), True
    row = connection.execute(
        """
        SELECT case_id FROM index_cases
        WHERE request_url = ? AND response_sha256 = ? AND accession = ?
          AND cohort_source_id = ?
        """,
        (request_url, digest, accession, cohort_source_id),
    ).fetchone()
    if row is None:
        raise IndexFixtureError("captured case disappeared during write")
    return int(row[0]), False


def _failure_code(error: str | None) -> str:
    if not error:
        return "unknown_error"
    if error.startswith("retries exhausted for"):
        return "retry_exhausted"
    if error.startswith("permanent error for"):
        return (
            "response_too_large"
            if "response exceeded" in error
            else "permanent_http_error"
        )
    return "broker_error"


def _finish_contribution(
    contributions: tuple[FixtureManifestContribution, ...],
    contribution: FixtureContribution,
    captured: int,
    failures: tuple[IndexCaptureFailure, ...],
) -> tuple[FixtureManifestContribution, ...]:
    updated = []
    for item in contributions:
        if item.request_fingerprint == contribution.request_fingerprint:
            updated.append(
                replace(
                    item,
                    captured_accessions=captured,
                    failed_accessions=len(failures),
                    state=(
                        "partial"
                        if failures or captured < contribution.accession_count
                        else "complete"
                    ),
                    finished_at=now_iso(),
                )
            )
        else:
            updated.append(item)
    return tuple(updated)


def capture_index_pages(
    cohort: InventoryCohort,
    *,
    fixture_id: str,
    paths: FixturePaths,
    broker: SecBroker,
    contribution: FixtureContribution,
) -> IndexCaptureResult:
    if not paths.manifest_path.is_file() or not paths.storage_path.is_file():
        raise IndexFixtureError(f"fixture does not exist: {paths.root}")
    if len(cohort.work_items) != contribution.accession_count:
        raise IndexFixtureError("cohort size differs from contribution accession_count")

    connection = sqlite3.connect(str(paths.storage_path))
    connection.execute("PRAGMA foreign_keys = ON")
    manifest = load_manifest(paths)
    if manifest.fixture_id != fixture_id:
        connection.close()
        raise IndexFixtureError("fixture id does not match its manifest")
    validate_database(connection, paths.storage_path, manifest.schema_version)
    contribution_state = _start_contribution(paths, connection, contribution)

    added = reused = cases_created = members_created = captured = 0
    failures: list[IndexCaptureFailure] = []
    observations = iter(
        groupby(cohort.observations, key=lambda observation: str(observation.accession))
    )
    try:
        for work_item in sorted(
            cohort.work_items, key=lambda item: str(item.accession)
        ):
            accession = str(work_item.accession)
            try:
                observation_accession, grouped = next(observations)
            except StopIteration as exc:
                raise IndexFixtureError("cohort work item has no observation") from exc
            if observation_accession != accession:
                raise IndexFixtureError("cohort observations and work items disagree")
            members = tuple(grouped)
            timestamp = now_iso()
            cached = _cached_digest(connection, accession, work_item.index_url)
            failure_code = None
            raw_error = None
            if cached is None:
                try:
                    response = broker.fetch(work_item.index_url)
                except Exception as exc:
                    response = {"status": "error", "error": str(exc)}
                if response.get("status") != "ok":
                    raw_error = str(response.get("error") or "")[:2000] or None
                    failure_code = _failure_code(raw_error)
                else:
                    body = response.get("payload") or b""
                    digest = sha256_bytes(body)
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO index_responses
                        (request_url, response_sha256, byte_size, compressed_body, captured_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            work_item.index_url,
                            digest,
                            len(body),
                            compress_payload(body),
                            timestamp,
                        ),
                    )
                    if cursor.rowcount:
                        added += 1
                    else:
                        reused += 1
                    cached = (digest, timestamp)
            else:
                reused += 1

            if failure_code is not None:
                failures.append(
                    IndexCaptureFailure(work_item.accession, failure_code, raw_error)
                )
                for member in members:
                    members_created += _record_member(
                        connection,
                        case_id=None,
                        accession=accession,
                        source_cik=str(member.source_cik),
                        cohort_source_id=member.cohort_source_id,
                        failure_code=failure_code,
                        raw_error=raw_error,
                        captured_at=timestamp,
                    )
            else:
                assert cached is not None
                digest = cached[0]
                for member in members:
                    case_id, created = _case_id(
                        connection,
                        request_url=work_item.index_url,
                        digest=digest,
                        accession=accession,
                        cohort_source_id=member.cohort_source_id,
                    )
                    cases_created += int(created)
                    members_created += _record_member(
                        connection,
                        case_id=case_id,
                        accession=accession,
                        source_cik=str(member.source_cik),
                        cohort_source_id=member.cohort_source_id,
                        failure_code=None,
                        raw_error=None,
                        captured_at=timestamp,
                    )
                captured += 1
            connection.commit()

        try:
            next(observations)
        except StopIteration:
            pass
        else:
            raise IndexFixtureError("cohort has observations without work items")

        finished = _finish_contribution(
            contribution_state, contribution, captured, tuple(failures)
        )
        validate_database(connection, paths.storage_path, SCHEMA_VERSION)
        refresh_manifest(paths, connection, finished)
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()

    return IndexCaptureResult(
        responses_added=added,
        responses_reused=reused,
        responses_processed=len(cohort.work_items),
        cases_created=cases_created,
        members_created=members_created,
        failures=tuple(failures),
    )
