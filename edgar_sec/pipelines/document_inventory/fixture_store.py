"""Append-only capture-and-replay store for EDGAR index pages.

Records compressed index-page bytes per access and replays them without the network.
Capture uses INSERT OR IGNORE; PRAGMA foreign_keys = ON is set per connection.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import zstandard as zstd

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.compression import compress_payload, decompress_payload
from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.infra.broker.sec_broker import SecBroker
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.domain.document_inventory.models import (
    CohortObservation,
    InventoryCohort,
)

_INDEX_FIXTURES_DB = "index_fixtures.sqlite"

#: Current store schema version; an integer, independent of the catalog string
#: versioning and bumped whenever a table's column layout changes.
SCHEMA_VERSION = 1

_TABLE_RESPONSES = "index_responses"
_TABLE_CASES = "index_cases"
_TABLE_COHORT_MEMBERS = "cohort_members"

_CREATE_RESPONSES = """
CREATE TABLE IF NOT EXISTS index_responses (
    request_url TEXT NOT NULL,
    response_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    compressed_body BLOB NOT NULL,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (request_url, response_sha256)
)
"""

_CREATE_CASES = """
CREATE TABLE IF NOT EXISTS index_cases (
    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_url TEXT NOT NULL,
    response_sha256 TEXT NOT NULL,
    accession TEXT NOT NULL,
    cohort_source_id TEXT NOT NULL,
    UNIQUE (request_url, response_sha256, accession, cohort_source_id),
    FOREIGN KEY (request_url, response_sha256) REFERENCES index_responses(request_url, response_sha256)
)
"""

_CREATE_COHORT_MEMBERS = """
CREATE TABLE IF NOT EXISTS cohort_members (
    member_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER,
    accession TEXT NOT NULL,
    source_cik TEXT NOT NULL,
    cohort_source_id TEXT NOT NULL,
    failure_code TEXT,
    raw_error TEXT,
    captured_at TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES index_cases(case_id)
)
"""

_INSERT_RESPONSES = f"""
INSERT OR IGNORE INTO {_TABLE_RESPONSES}
(request_url, response_sha256, byte_size, compressed_body, captured_at)
VALUES (?, ?, ?, ?, ?)
"""

_INSERT_CASE = f"""
INSERT OR IGNORE INTO {_TABLE_CASES}
(request_url, response_sha256, accession, cohort_source_id)
VALUES (?, ?, ?, ?)
"""

_INSERT_COHORT_MEMBER = f"""
INSERT INTO {_TABLE_COHORT_MEMBERS}
(case_id, accession, source_cik, cohort_source_id, failure_code, raw_error, captured_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""


@dataclass(frozen=True, slots=True)
class IndexResponseKey:
    """The identity of one captured index page: request URL plus page digest."""

    request_url: str
    response_sha256: str


@dataclass(frozen=True, slots=True)
class CapturedIndexPage:
    """A replayed index page: bytes on disk, digest and provenance on disk."""

    request_url: str
    response_sha256: str
    byte_size: int
    compressed_body: bytes
    captured_at: str


@dataclass(frozen=True, slots=True)
class IndexCaptureFailure:
    """A capture failure for one observation of an index page."""

    accession: AccessionNumber
    failure_code: str
    raw_broker_error: str | None


@dataclass(frozen=True, slots=True)
class IndexCaptureResult:
    """Per-run capture summary: page upsert counts, case rows, and failures."""

    responses_added: int
    responses_reused: int
    responses_processed: int
    cases_created: int
    accessions_seen: int
    failures: tuple[IndexCaptureFailure, ...]


@dataclass(frozen=True, slots=True)
class IndexFixturePaths:
    """File layout for one index-fixture run.

    ``root`` holds ``manifest.json`` and ``index_fixtures.sqlite``; tests pass a plain
    ``Path`` root and the functions build the layout.
    """

    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def database_path(self) -> Path:
        return self.root / _INDEX_FIXTURES_DB


@dataclass(frozen=True, slots=True)
class IndexFixtureManifest:
    """Published manifest for one index fixture.

    The provisional manifest leaves ``database_sha256``/``page_count``/counts empty
    until ``publish_index_fixture`` finalizes it.
    """

    fixture_id: str
    schema_version: int
    database_path: str
    database_sha256: str | None
    page_count: int
    accession_count: int
    cohort_source_ids: tuple[str, ...]


class IndexFixtureError(RuntimeError):
    """A fixture is missing, malformed, or could not be accessed."""


def _now_iso() -> str:
    return datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat()


def _resolve(paths: Path | IndexFixturePaths) -> IndexFixturePaths:
    if isinstance(paths, Path):
        return IndexFixturePaths(root=paths)
    return paths


def _open_writable(db_path: Path) -> sqlite3.Connection:
    """Open the fixture database for writes, with WAL mode and foreign keys on."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(db_path.resolve()), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _validate_table_schema(
    conn: sqlite3.Connection,
    path: Path,
    table: str,
    expected: tuple[str, ...],
) -> None:
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    actual = tuple(row[1] for row in columns)
    if actual != expected:
        raise IndexFixtureError(
            f"invalid {table} schema in {path}; expected {expected}, got {actual}"
        )


def _failure_code_for_broker_error(raw: str | None) -> str:
    """Map the broker's raw error string to a stable ``IndexCaptureFailure`` code.

    Infers the exception class from the recognizable prefix; the full raw string is
    preserved in ``IndexCaptureFailure.raw_broker_error``.
    """
    if not raw:
        return "unknown_error"
    if raw.startswith("retries exhausted for"):
        return "retry_exhausted"
    if raw.startswith("permanent error for"):
        return (
            "response_too_large"
            if "response exceeded" in raw
            else "permanent_http_error"
        )
    if raw.startswith("broker"):
        return "broker_error"
    return "unknown_error"


def create_index_fixture(
    paths: Path | IndexFixturePaths, *, fixture_id: str
) -> IndexFixtureManifest:
    """Create an empty index fixture: DB with tables and a provisional manifest.

    ``fixture_id`` identifies the fixture; the manifest is finalized by
    ``publish_index_fixture``. The DB is created in WAL mode with foreign keys on.
    """
    paths = _resolve(paths)
    manifest_path = paths.manifest_path
    database_path = paths.database_path
    if manifest_path.is_file():
        raise IndexFixtureError(f"fixture already created: {manifest_path}")
    if database_path.exists():
        conn = sqlite3.connect(str(database_path))
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "index_responses" not in tables:
                raise IndexFixtureError(
                    f"database {database_path} exists but is not an index fixture store"
                )
            raise IndexFixtureError(f"database already exists: {database_path}")
        finally:
            conn.close()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open_writable(database_path)
    try:
        conn.execute(_CREATE_RESPONSES)
        conn.execute(_CREATE_CASES)
        conn.execute(_CREATE_COHORT_MEMBERS)
        conn.commit()
    finally:
        conn.close()
    manifest = IndexFixtureManifest(
        fixture_id=fixture_id,
        schema_version=SCHEMA_VERSION,
        database_path=_INDEX_FIXTURES_DB,
        database_sha256=None,
        page_count=0,
        accession_count=0,
        cohort_source_ids=(),
    )
    atomic_write_json(manifest_path, asdict(manifest))
    return manifest


def capture_index_pages(
    cohort: InventoryCohort,
    *,
    fixture_id: str,
    paths: Path | IndexFixturePaths,
    broker: SecBroker,
) -> IndexCaptureResult:
    """Fetch every index page in ``cohort`` and record the results append-only.

    Pages are upserted by ``(request_url, response_sha256)``, so re-capturing is
    idempotent; broker failures become ``IndexCaptureFailure`` entries.
    """
    paths = _resolve(paths)
    if not paths.manifest_path.is_file():
        raise IndexFixtureError(
            f"no manifest found; run create_index_fixture first: {paths.manifest_path}"
        )
    if not paths.database_path.is_file():
        raise IndexFixtureError(f"fixture database missing: {paths.database_path}")
    conn = sqlite3.connect(str(paths.database_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if tables - {"sqlite_sequence"} != {
            "index_responses",
            "index_cases",
            "cohort_members",
        }:
            raise IndexFixtureError(
                f"fixture database {paths.database_path} is not an index fixture store"
            )
    except Exception:
        conn.close()
        raise
    accession_to_url = {wi.accession: wi.index_url for wi in cohort.work_items}
    url_to_obs: dict[str, list[CohortObservation]] = {}
    for obs in cohort.observations:
        url = accession_to_url.get(obs.accession)
        if url is None:
            raise IndexFixtureError(
                f"observation has no work item for accession {obs.accession}"
            )
        url_to_obs.setdefault(url, []).append(obs)
    added = reused = cases_created = accessions_seen = 0
    failures: list[IndexCaptureFailure] = []
    for wi in cohort.work_items:
        url = wi.index_url
        obs_list = url_to_obs[url]
        timestamp = _now_iso()
        result = broker.fetch(url)
        if result.get("status") != "ok":
            for obs in obs_list:
                failures.append(
                    IndexCaptureFailure(
                        accession=obs.accession,
                        failure_code=_failure_code_for_broker_error(
                            result.get("error")
                        ),
                        raw_broker_error=result.get("error"),
                    )
                )
                conn.execute(
                    _INSERT_COHORT_MEMBER,
                    (
                        None,
                        str(obs.accession),
                        str(obs.source_cik),
                        obs.cohort_source_id,
                        failures[-1].failure_code,
                        failures[-1].raw_broker_error,
                        timestamp,
                    ),
                )
            conn.commit()
            continue
        content = result.get("payload") or b""
        compressed = compress_payload(content)
        digest = sha256_bytes(content)
        cur = conn.execute(
            _INSERT_RESPONSES, (url, digest, len(content), compressed, timestamp)
        )
        if cur.rowcount:
            added += 1
            for obs in obs_list:
                cur = conn.execute(
                    _INSERT_CASE,
                    (url, digest, str(obs.accession), obs.cohort_source_id),
                )
                if cur.rowcount:
                    cases_created += 1
                    member_case_id = cur.lastrowid  # type: ignore[assignment]
                else:
                    row = conn.execute(
                        "SELECT case_id FROM index_cases WHERE request_url = ? AND response_sha256 = ? AND accession = ? AND cohort_source_id = ?",
                        (url, digest, str(obs.accession), obs.cohort_source_id),
                    ).fetchone()
                    member_case_id = row[0]  # type: ignore[union-attr]
                conn.execute(
                    _INSERT_COHORT_MEMBER,
                    (
                        member_case_id,
                        str(obs.accession),
                        str(obs.source_cik),
                        obs.cohort_source_id,
                        None,
                        None,
                        timestamp,
                    ),
                )
                accessions_seen += 1
        else:
            reused += 1
        conn.commit()
    return IndexCaptureResult(
        responses_added=added,
        responses_reused=reused,
        responses_processed=len(cohort.work_items),
        cases_created=cases_created,
        accessions_seen=accessions_seen,
        failures=tuple(failures),
    )


def publish_index_fixture(paths: Path | IndexFixturePaths) -> IndexFixtureManifest:
    """Finalize an index fixture: checkpoint, digest, and atomically publish the manifest.

    The ``database_sha256`` is verified at replay, so the fixture must pass publish
    before it can be consumed; a modified file will be refused.
    """
    paths = _resolve(paths)
    database_path = paths.database_path
    manifest_path = paths.manifest_path
    if not database_path.is_file():
        raise IndexFixtureError(f"fixture database missing: {database_path}")
    if not manifest_path.is_file():
        raise IndexFixtureError(f"no manifest found: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = IndexFixtureManifest(**data)
    if manifest.schema_version != SCHEMA_VERSION:
        raise IndexFixtureError(
            f"fixture schema_version {manifest.schema_version} != {SCHEMA_VERSION}"
        )
    if manifest.database_sha256 is not None:
        raise IndexFixtureError(f"fixture already published: {manifest_path}")
    conn = sqlite3.connect(str(database_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db_digest = sha256_bytes(database_path.read_bytes())
        page_count = conn.execute(
            f"SELECT COUNT(*) FROM {_TABLE_RESPONSES}"
        ).fetchone()[0]
        accession_count = conn.execute(
            f"SELECT COUNT(*) FROM {_TABLE_CASES}"
        ).fetchone()[0]
        source_ids = tuple(
            row[0]
            for row in conn.execute(
                f"SELECT DISTINCT cohort_source_id FROM {_TABLE_COHORT_MEMBERS}"
            ).fetchall()
        )
    finally:
        conn.close()
    published = IndexFixtureManifest(
        fixture_id=manifest.fixture_id,
        schema_version=manifest.schema_version,
        database_path=manifest.database_path,
        database_sha256=db_digest,
        page_count=page_count,
        accession_count=accession_count,
        cohort_source_ids=source_ids,
    )
    atomic_write_json(manifest_path, asdict(published))
    ro = _open_readonly(database_path)
    try:
        _validate_table_schema(
            ro,
            database_path,
            _TABLE_RESPONSES,
            (
                "request_url",
                "response_sha256",
                "byte_size",
                "compressed_body",
                "captured_at",
            ),
        )
        _validate_table_schema(
            ro,
            database_path,
            _TABLE_CASES,
            (
                "case_id",
                "request_url",
                "response_sha256",
                "accession",
                "cohort_source_id",
            ),
        )
        _validate_table_schema(
            ro,
            database_path,
            _TABLE_COHORT_MEMBERS,
            (
                "member_id",
                "case_id",
                "accession",
                "source_cik",
                "cohort_source_id",
                "failure_code",
                "raw_error",
                "captured_at",
            ),
        )
        if sha256_bytes(database_path.read_bytes()) != published.database_sha256:
            raise IndexFixtureError("database digest mismatch after publish")
        if page_count == 0 or accession_count == 0:
            raise IndexFixtureError("cannot publish an empty fixture")
        written = IndexFixtureManifest(
            **json.loads(manifest_path.read_text(encoding="utf-8"))
        )
        if written.database_sha256 != published.database_sha256:
            raise IndexFixtureError("written manifest digest mismatch")
    finally:
        ro.close()
    return published


def list_index_cases(
    paths: Path | IndexFixturePaths, accession: AccessionNumber | str
) -> tuple[IndexResponseKey, ...]:
    """Return the captured index-page keys for an accession, in stable sorted order.

    Validates the manifest when present, then opens the database read-only.
    """
    paths = _resolve(paths)
    database_path = paths.database_path
    if not database_path.is_file():
        raise IndexFixtureError(f"fixture database not found: {database_path}")
    if paths.manifest_path.is_file():
        data = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
        manifest = IndexFixtureManifest(**data)
        if manifest.schema_version != SCHEMA_VERSION:
            raise IndexFixtureError(
                f"fixture schema_version {manifest.schema_version} != {SCHEMA_VERSION}"
            )
        if (
            manifest.database_sha256
            and sha256_bytes(database_path.read_bytes()) != manifest.database_sha256
        ):
            raise IndexFixtureError(
                "fixture database digest no longer matches manifest"
            )
    ro = _open_readonly(database_path)
    try:
        a = str(accession) if isinstance(accession, AccessionNumber) else accession
        rows = ro.execute(
            f"SELECT request_url, response_sha256 FROM {_TABLE_CASES} WHERE accession = ? ORDER BY request_url, response_sha256",
            (a,),
        ).fetchall()
        return tuple(IndexResponseKey(r[0], r[1]) for r in rows)
    finally:
        ro.close()


def replay_index_page(
    paths: Path | IndexFixturePaths,
    accession: AccessionNumber | str,
    key: IndexResponseKey,
) -> CapturedIndexPage:
    """Replay one captured index page's raw bytes from the fixture store.

    Validates the manifest schema and file digest, then verifies the requested
    case key before returning the (de)compressed page bytes.
    """
    paths = _resolve(paths)
    database_path = paths.database_path
    manifest_path = paths.manifest_path
    if not database_path.is_file():
        raise IndexFixtureError(f"fixture database not found: {database_path}")
    if not manifest_path.is_file():
        raise IndexFixtureError(f"fixture manifest not found: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = IndexFixtureManifest(**data)
    if manifest.schema_version != SCHEMA_VERSION:
        raise IndexFixtureError(
            f"fixture schema_version {manifest.schema_version} != {SCHEMA_VERSION}"
        )
    if manifest.database_sha256 is None:
        raise IndexFixtureError("fixture not published; no database digest in manifest")
    if sha256_bytes(database_path.read_bytes()) != manifest.database_sha256:
        raise IndexFixtureError("fixture database digest no longer matches manifest")
    ro = _open_readonly(database_path)
    try:
        a = str(accession) if isinstance(accession, AccessionNumber) else accession
        row = ro.execute(
            f"""
            SELECT i.request_url, i.response_sha256, i.byte_size, i.compressed_body, i.captured_at
            FROM {_TABLE_CASES} c
            JOIN {_TABLE_RESPONSES} i
            ON c.request_url = i.request_url AND c.response_sha256 = i.response_sha256
            WHERE c.accession = ? AND c.request_url = ? AND c.response_sha256 = ?
            """,
            (a, key.request_url, key.response_sha256),
        ).fetchone()
        if not row:
            raise IndexFixtureError(
                f"no captured page for accession {a} and key ({key.request_url}, {key.response_sha256})"
            )
        if row[1] != key.response_sha256:
            raise IndexFixtureError(f"case key hash mismatch for {key.request_url}")
        try:
            body = decompress_payload(bytes(row[3]))
        except zstd.ZstdError as exc:
            raise IndexFixtureError(
                f"cannot decompress page for {key.request_url}: {exc}"
            ) from exc
        if sha256_bytes(body) != key.response_sha256:
            raise IndexFixtureError("decompressed body hash does not match key")
        return CapturedIndexPage(
            request_url=str(row[0]),
            response_sha256=str(row[1]),
            byte_size=int(row[2]),
            compressed_body=row[3],
            captured_at=str(row[4]),
        )
    finally:
        ro.close()
