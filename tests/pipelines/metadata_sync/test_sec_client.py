"""Submissions client fan-out: a per-file failure is recorded, not raised, so the
engine decides ``partial`` versus ``failed`` downstream.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.domain.sec_urls import historical_submissions_url, submissions_url
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.sec_http.client import SecHttpClient
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


def test_client_builds_from_resolved_settings() -> None:
    """Every other test injects a fake transport, so only this reaches the chain."""
    from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
    from edgar_sec.pipelines.metadata_sync.cli import _build_client

    settings = resolve_runtime_settings().sec
    client = _build_client()
    assert client.http.user_agent == settings.user_agent
    assert client.http.timeout_s == settings.timeout_s
    assert client.http.retry_policy.max_retries == settings.max_retries


def test_cache_configuration_is_forwarded_to_the_http_client(tmp_path: Path) -> None:
    """Without a forwarded cache root there is no cache and no failure ledger."""
    client = SubmissionsClient(
        settings=resolve_runtime_settings().sec,
        cache_dir=tmp_path,
        ttl_s=1234,
    )
    assert client.http.cache_dir == tmp_path.resolve()
    assert client.http._cache is not None
    assert client.http._cache.ttl_s == 1234
    assert client.http._cache.db_path == tmp_path.resolve() / "responses.sqlite"


def test_a_cached_url_is_served_without_touching_the_transport(tmp_path: Path) -> None:
    """A cache hit must not consume a request-budget slot."""

    class Tripwire:
        def get(self, *_args, **_kwargs):
            raise AssertionError("the transport was reached for a cached URL")

    http = SecHttpClient(
        user_agent="Cache Probe probe@example.com",
        cache_dir=tmp_path,
        ttl_s=600,
        session_factory=Tripwire,
    )
    http._cache.put(
        "https://data.sec.gov/submissions/CIK0000000020.json",
        b'{"cik":"20"}',
        "d41d8cd98f00b204e9800998ecf8427e",
        12,
        "application/json",
    )

    client = SubmissionsClient(http=http)
    result = client.fetch_cik("0000000020")

    assert result.fetched_ok is True
    assert result.payload == {"cik": "20"}
    assert result.terminal_error() is None
