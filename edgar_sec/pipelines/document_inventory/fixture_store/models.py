"""Typed records and SQLite schema for local index-page fixtures."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.identity import AccessionNumber

SCHEMA_VERSION = 2

_CREATE_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS index_responses (
        request_url TEXT NOT NULL,
        response_sha256 TEXT NOT NULL,
        byte_size INTEGER NOT NULL,
        compressed_body BLOB NOT NULL,
        captured_at TEXT NOT NULL,
        PRIMARY KEY (request_url, response_sha256)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_cases (
        case_id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_url TEXT NOT NULL,
        response_sha256 TEXT NOT NULL,
        accession TEXT NOT NULL,
        cohort_source_id TEXT NOT NULL,
        UNIQUE (request_url, response_sha256, accession, cohort_source_id),
        FOREIGN KEY (request_url, response_sha256)
            REFERENCES index_responses(request_url, response_sha256)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cohort_members (
        member_id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id INTEGER,
        accession TEXT NOT NULL,
        source_cik TEXT NOT NULL,
        cohort_source_id TEXT NOT NULL,
        failure_code TEXT,
        raw_error TEXT,
        captured_at TEXT NOT NULL,
        UNIQUE (accession, source_cik, cohort_source_id),
        FOREIGN KEY (case_id) REFERENCES index_cases(case_id)
    )
    """,
)

EXPECTED_COLUMNS = {
    "index_responses": (
        "request_url",
        "response_sha256",
        "byte_size",
        "compressed_body",
        "captured_at",
    ),
    "index_cases": (
        "case_id",
        "request_url",
        "response_sha256",
        "accession",
        "cohort_source_id",
    ),
    "cohort_members": (
        "member_id",
        "case_id",
        "accession",
        "source_cik",
        "cohort_source_id",
        "failure_code",
        "raw_error",
        "captured_at",
    ),
}


@dataclass(frozen=True, slots=True)
class IndexResponseKey:
    request_url: str
    response_sha256: str


@dataclass(frozen=True, slots=True)
class CapturedIndexCase:
    accession: AccessionNumber
    key: IndexResponseKey


@dataclass(frozen=True, slots=True)
class CapturedIndexPage:
    accession: AccessionNumber
    key: IndexResponseKey
    body: bytes
    captured_at: str

    @property
    def request_url(self) -> str:
        return self.key.request_url

    @property
    def response_sha256(self) -> str:
        return self.key.response_sha256

    @property
    def byte_size(self) -> int:
        return len(self.body)


@dataclass(frozen=True, slots=True)
class FixtureContribution:
    plan_id: str
    catalog_id: str
    scope: str
    plan_schema_version: str
    request_fingerprint: str
    accession_count: int


@dataclass(frozen=True, slots=True)
class FixtureManifestContribution:
    plan_id: str
    catalog_id: str
    scope: str
    plan_schema_version: str
    request_fingerprint: str
    accession_count: int
    captured_accessions: int
    failed_accessions: int
    state: str
    started_at: str
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class IndexFixtureManifest:
    fixture_id: str
    schema_version: int
    capture_state: str
    contributions: tuple[FixtureManifestContribution, ...]
    page_count: int
    accession_count: int
    membership_count: int


@dataclass(frozen=True, slots=True)
class IndexCaptureFailure:
    accession: AccessionNumber
    failure_code: str
    raw_broker_error: str | None


@dataclass(frozen=True, slots=True)
class IndexCaptureResult:
    responses_added: int
    responses_reused: int
    responses_processed: int
    cases_created: int
    members_created: int
    failures: tuple[IndexCaptureFailure, ...]


@dataclass(frozen=True, slots=True)
class FixtureListStatus:
    fixture_id: str | None
    state: str
    schema_version: int | None
    database_exists: bool
    database_integrity_ok: bool | None
    page_count: int
    accession_count: int
    membership_count: int
    contributions: tuple[FixtureManifestContribution, ...]


class IndexFixtureError(RuntimeError):
    """A fixture is missing, malformed, or inconsistent."""
