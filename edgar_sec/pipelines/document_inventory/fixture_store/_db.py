"""SQLite connections, manifest IO, and fixture integrity validation."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from edgar_sec.foundation.runtime.fixtures import (
    FixtureManifestEnvelope,
    FixturePaths,
)
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    EXPECTED_COLUMNS,
    SCHEMA_VERSION,
    FixtureManifestContribution,
    IndexFixtureError,
    IndexFixtureManifest,
)

_COMMITTED_TABLES = {"index_responses", "index_cases", "cohort_members"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_writable(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path))
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def open_readonly(database_path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(database_path.resolve()), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def load_manifest(paths: FixturePaths) -> IndexFixtureManifest:
    try:
        raw = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
        envelope = FixtureManifestEnvelope.from_mapping(raw)
        if (
            envelope.fixture_kind != "document_inventory.index_pages"
            or envelope.fixture_id != paths.root.name
            or envelope.storage_format != "sqlite"
            or envelope.storage_path != paths.storage_filename
        ):
            raise ValueError("fixture envelope identity or storage does not match")
        details = envelope.details
        contributions = tuple(
            FixtureManifestContribution(**item) for item in details["contributions"]
        )
        return IndexFixtureManifest(
            fixture_id=envelope.fixture_id,
            schema_version=details["store_schema_version"],
            capture_state=details["capture_state"],
            contributions=contributions,
            page_count=details["page_count"],
            accession_count=details["accession_count"],
            membership_count=details["membership_count"],
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise IndexFixtureError(
            f"invalid fixture manifest: {paths.manifest_path}"
        ) from exc


def write_manifest(paths: FixturePaths, manifest: IndexFixtureManifest) -> None:
    now = now_iso()
    created = now
    if paths.manifest_path.is_file():
        try:
            prior = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
            prior_envelope = FixtureManifestEnvelope.from_mapping(prior)
            if (
                prior_envelope.fixture_kind != "document_inventory.index_pages"
                or prior_envelope.fixture_id != manifest.fixture_id
                or prior_envelope.storage_format != "sqlite"
                or prior_envelope.storage_path != paths.storage_filename
            ):
                raise ValueError("fixture envelope identity or storage does not match")
            created = prior_envelope.created_at
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise IndexFixtureError(
                f"invalid fixture manifest: {paths.manifest_path}"
            ) from exc
    details = {
        "store_schema_version": manifest.schema_version,
        "capture_state": manifest.capture_state,
        "contributions": [asdict(item) for item in manifest.contributions],
        "page_count": manifest.page_count,
        "accession_count": manifest.accession_count,
        "membership_count": manifest.membership_count,
    }
    envelope = FixtureManifestEnvelope(
        fixture_kind="document_inventory.index_pages",
        fixture_id=manifest.fixture_id,
        storage_format="sqlite",
        storage_path=paths.storage_filename,
        created_at=created,
        updated_at=now,
        details=details,
    )
    atomic_write_json(paths.manifest_path, envelope.to_mapping(), indent=2)


def validate_database(
    connection: sqlite3.Connection, database_path: Path, schema_version: int
) -> None:
    if type(schema_version) is not int:
        raise IndexFixtureError("fixture schema_version must be an integer")
    if schema_version != SCHEMA_VERSION:
        raise IndexFixtureError(
            f"fixture schema_version {schema_version} != {SCHEMA_VERSION}"
        )
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if tables - {"sqlite_sequence"} != _COMMITTED_TABLES:
        raise IndexFixtureError(
            f"database {database_path} is not an index fixture store"
        )
    for table, expected in EXPECTED_COLUMNS.items():
        actual = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM pragma_table_info(?)", [table]
            )
        )
        if actual != expected:
            raise IndexFixtureError(f"invalid {table} schema in {database_path}")
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if not integrity or integrity[0] != "ok":
        raise IndexFixtureError(f"database {database_path} failed integrity validation")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise IndexFixtureError(f"database {database_path} has invalid references")


def count_rows(connection: sqlite3.Connection, table: str) -> int:
    queries = {
        "index_responses": "SELECT COUNT(*) FROM index_responses",
        "index_cases": "SELECT COUNT(*) FROM index_cases",
        "cohort_members": "SELECT COUNT(*) FROM cohort_members",
    }
    try:
        query = queries[table]
    except KeyError as exc:
        raise ValueError(f"unknown fixture table: {table}") from exc
    return int(connection.execute(query).fetchone()[0])


def distinct_accession_count(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT accession FROM index_cases)"
        ).fetchone()[0]
    )


def membership_count(connection: sqlite3.Connection) -> int:
    return count_rows(connection, "cohort_members")


def manifest_state(
    contributions: tuple[FixtureManifestContribution, ...],
) -> str:
    if not contributions:
        return "empty"
    states = {item.state for item in contributions}
    if "capturing" in states:
        return "interrupted"
    if "partial" in states:
        return "partial"
    return "complete"


def refresh_manifest(
    paths: FixturePaths,
    connection: sqlite3.Connection,
    contributions: tuple[FixtureManifestContribution, ...],
) -> IndexFixtureManifest:
    manifest = IndexFixtureManifest(
        fixture_id=load_manifest(paths).fixture_id,
        schema_version=SCHEMA_VERSION,
        capture_state=manifest_state(contributions),
        contributions=contributions,
        page_count=count_rows(connection, "index_responses"),
        accession_count=distinct_accession_count(connection),
        membership_count=membership_count(connection),
    )
    write_manifest(paths, manifest)
    return manifest
