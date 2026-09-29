"""Submissions client fan-out tests, offline via the injected transport.

The client owns the fan-out from one CIK to its main document plus every
historical file. Historical files are required inputs rather than extras, so a
per-file failure is recorded on the result instead of raised, and the engine
decides ``partial`` versus ``failed`` downstream.
"""

from __future__ import annotations

from edgar_sec.domain.sec_urls import historical_submissions_url, submissions_url
from edgar_sec.pipelines.metadata_sync.sec_client import (
    CikFetchResult,
    SubmissionsClient,
)
from tests.support import FakeSession, build_test_client, load_fixture

FORD = "0000037996"
FORD_HIST = "CIK0000037996-submissions-001.json"


def _payload(**extra) -> dict:
    return {
        "name": "FORD MOTOR CO",
        "filings": {
            "recent": {
                "accessionNumber": [f"{FORD}-26-000001"],
                "filingDate": ["2026-01-02"],
                "form": ["10-K"],
                "size": [1024],
            },
            "files": [],
        },
        **extra,
    }


def test_fetch_cik_records_provenance(session: FakeSession) -> None:
    session.register(submissions_url(FORD), load_fixture("recent_submissions.json"))
    result = build_test_client(session).fetch_cik(FORD)

    assert result.cik_padded == FORD
    assert result.source_url == submissions_url(FORD)
    assert result.fetched_ok is True
    assert result.permanent_error is None
    assert result.terminal_error() is None
    assert result.payload["name"]
    assert result.byte_count > 0
    assert len(result.response_sha256) == 64


def test_fetch_cik_follows_historical_file_references(session: FakeSession) -> None:
    session.register(submissions_url(FORD), load_fixture("recent_submissions.json"))
    session.register(
        historical_submissions_url(FORD_HIST),
        load_fixture("historical_submissions.json"),
    )
    result = build_test_client(session).fetch_cik(FORD)

    assert result.historical_files_fetched == 1
    assert result.historical_errors == []
    file_url, name, payload = result.historical_payloads[0]
    assert file_url == historical_submissions_url(FORD_HIST)
    assert name == FORD_HIST
    assert isinstance(payload, dict)


def test_a_missing_historical_file_is_recorded_not_raised(
    session: FakeSession,
) -> None:
    session.register(submissions_url(FORD), load_fixture("recent_submissions.json"))
    result = build_test_client(session).fetch_cik(FORD)

    assert result.fetched_ok is True
    assert result.historical_files_fetched == 0
    assert len(result.historical_errors) == 1
    assert FORD_HIST in result.historical_errors[0]


def test_a_missing_submissions_document_is_permanent(session: FakeSession) -> None:
    result = build_test_client(session).fetch_cik(FORD)
    assert result.fetched_ok is False
    assert result.permanent_error
    assert result.terminal_error() == result.permanent_error
    assert result.payload is None


def test_a_non_object_payload_is_permanent(session: FakeSession) -> None:
    """A JSON array is rejected permanently at the transport boundary."""
    session.register(submissions_url(FORD), [1, 2, 3])
    result = build_test_client(session).fetch_cik(FORD)
    assert result.fetched_ok is False
    assert result.terminal_error()
    assert result.payload is None


def test_terminal_error_prefers_permanent_over_transient() -> None:
    result = CikFetchResult(cik_padded=FORD)
    assert result.terminal_error() is None
    result.transient_error = "timeout"
    assert result.terminal_error() == "timeout"
    result.permanent_error = "not found"
    assert result.terminal_error() == "not found"


def test_malformed_historical_descriptors_are_ignored() -> None:
    assert SubmissionsClient._historical_names({"filings": {}}) == []
    assert SubmissionsClient._historical_names({"filings": {"files": "nope"}}) == []
    assert SubmissionsClient._historical_names(
        {"filings": {"files": [{"name": "a.json"}, "junk", {}]}}
    ) == ["a.json"]


def test_client_requires_an_identity_source() -> None:
    try:
        SubmissionsClient()
    except ValueError as exc:
        assert "user_agent or settings is required" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_client_accepts_an_explicit_user_agent(session: FakeSession) -> None:
    client = SubmissionsClient(http=build_test_client(session).http)
    session.register(submissions_url(FORD), _payload())
    assert client.fetch_cik(FORD).fetched_ok is True
