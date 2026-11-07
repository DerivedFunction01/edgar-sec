"""Submissions client fan-out: a per-file failure is recorded, not raised, so the
engine decides ``partial`` versus ``failed`` downstream.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.domain.sec_urls import historical_submissions_url, submissions_url
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.pipelines.metadata_sync.sec_client import (
    BulkSubmissionsClient,
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


def _write_bulk_zip(path: Path, members: dict[str, bytes]) -> Path:
    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return path


def _bulk_members() -> dict[str, bytes]:
    import json as json_module

    main = _payload()
    main["filings"]["files"] = [
        {"name": FORD_HIST, "filingFrom": "2020-01-01", "filingTo": "2020-12-31"}
    ]
    shard = {
        "accessionNumber": [f"{FORD}-20-000009"],
        "filingDate": ["2020-03-01"],
        "reportDate": ["2019-12-31"],
        "form": ["10-K"],
        "primaryDocument": ["ford-10k.htm"],
    }
    return {
        f"CIK{FORD}.json": json_module.dumps(main).encode("utf-8"),
        FORD_HIST: json_module.dumps(shard).encode("utf-8"),
    }


def test_bulk_archive_yields_payload_history_and_provenance(tmp_path: Path) -> None:
    from edgar_sec.domain.sec_urls import submissions_bulk_url
    from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
    from edgar_sec.pipelines.metadata_sync.sec_client import BulkSubmissionsArchive

    members = _bulk_members()
    zip_path = _write_bulk_zip(tmp_path / "submissions.zip", members)
    archive = BulkSubmissionsArchive(zip_path)
    client = BulkSubmissionsClient(archive)
    result = client.fetch_cik(FORD)

    assert result.fetched_ok is True
    assert result.payload is not None and result.payload["name"] == "FORD MOTOR CO"
    assert result.historical_files_fetched == 1
    assert result.historical_errors == []
    file_url, name, _hist = result.historical_payloads[0]
    assert (file_url, name) == (historical_submissions_url(FORD_HIST), FORD_HIST)
    assert result.source_kind == "bulk"
    assert result.source_url == submissions_bulk_url()
    assert result.source_archive_sha256 == file_sha256(zip_path)
    assert result.response_sha256 == sha256_bytes(members[f"CIK{FORD}.json"])
    assert result.byte_count == len(members[f"CIK{FORD}.json"])


def test_bulk_archive_missing_cik_is_a_permanent_error(tmp_path: Path) -> None:
    from edgar_sec.pipelines.metadata_sync.sec_client import BulkSubmissionsArchive

    archive = BulkSubmissionsArchive(
        _write_bulk_zip(tmp_path / "s.zip", _bulk_members())
    )
    result = archive.result_for("0000999999")

    assert result.fetched_ok is False
    assert result.permanent_error is not None
    assert result.terminal_error() == result.permanent_error


def test_bulk_archive_bad_member_is_per_cik_and_others_survive(
    tmp_path: Path,
) -> None:
    from edgar_sec.pipelines.metadata_sync.sec_client import BulkSubmissionsArchive

    members = _bulk_members()
    members["CIK0000999999.json"] = b"{broken"
    archive = BulkSubmissionsArchive(_write_bulk_zip(tmp_path / "s.zip", members))

    broken = archive.result_for("0000999999")
    healthy = archive.result_for(FORD)

    assert broken.permanent_error is not None and broken.payload is None
    assert healthy.fetched_ok is True


def test_bulk_archive_missing_shard_is_a_historical_error(tmp_path: Path) -> None:
    from edgar_sec.pipelines.metadata_sync.sec_client import BulkSubmissionsArchive

    members = _bulk_members()
    del members[FORD_HIST]
    archive = BulkSubmissionsArchive(_write_bulk_zip(tmp_path / "s.zip", members))
    result = archive.result_for(FORD)

    assert result.fetched_ok is True
    assert result.historical_files_fetched == 0
    assert len(result.historical_errors) == 1
    assert FORD_HIST in result.historical_errors[0]


def test_bulk_rows_match_per_cik_rows(session: FakeSession, tmp_path: Path) -> None:
    """Bulk and per-CIK paths normalize to the same rows, history included."""
    import json as json_module

    from edgar_sec.engine.submissions.builder import normalize_submissions
    from edgar_sec.pipelines.metadata_sync.sec_client import BulkSubmissionsArchive

    members = _bulk_members()
    main = json_module.loads(members[f"CIK{FORD}.json"])
    shard = json_module.loads(members[FORD_HIST])
    session.register(submissions_url(FORD), main)
    session.register(historical_submissions_url(FORD_HIST), shard)
    live = build_test_client(session).fetch_cik(FORD)
    bulk = BulkSubmissionsArchive(
        _write_bulk_zip(tmp_path / "s.zip", members)
    ).result_for(FORD)

    def _row(result: CikFetchResult) -> dict:
        return normalize_submissions(
            result.payload or {},
            cik_padded=FORD,
            input_name="test",
            snapshot_id="snap-1",
            fetched_at="2026-01-01T00:00:00Z",
            source_url=result.source_url,
            byte_count=result.byte_count,
            historical_payloads=result.historical_payloads,
            historical_errors=result.historical_errors,
            response_sha256=result.response_sha256,
            input_fingerprint="fp",
            chunk_id=0,
        )

    live_row, bulk_row = _row(live), _row(bulk)
    assert bulk_row["status"] == live_row["status"] == "ok"
    # Filing rows differ only in source_file, the per-fetch provenance stamp.
    strip = lambda rows: [  # noqa: E731
        {k: v for k, v in row.items() if k != "source_file"} for row in rows
    ]
    assert strip(bulk_row["filings"]) == strip(live_row["filings"])
    assert len(bulk_row["filings"]) == 2
    from edgar_sec.domain.sec_urls import submissions_bulk_url

    assert {row["source_file"] for row in bulk_row["filings"]} == {
        submissions_bulk_url(),
        historical_submissions_url(FORD_HIST),
    }
    assert {row["source_file"] for row in live_row["filings"]} == {
        submissions_url(FORD),
        historical_submissions_url(FORD_HIST),
    }
    assert bulk_row["historical_files_total"] == live_row["historical_files_total"]
    assert bulk_row["identity"] == live_row["identity"]


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
    from edgar_sec.pipelines.metadata_sync.commands.client import build_client

    settings = resolve_runtime_settings().sec
    client = build_client()
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


class _StreamingHttp:
    """Fake transport honoring the real ``stream_to_file`` call shape."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def stream_to_file(
        self, url, destination, *, max_response_bytes, validate_redirect
    ):
        from edgar_sec.foundation.hashing import sha256_bytes
        from edgar_sec.infra.sec_http.streaming import StreamedResponse

        validate_redirect(url)
        Path(destination).write_bytes(self.payload)
        self.calls.append({"url": url, "max_response_bytes": max_response_bytes})
        return StreamedResponse(
            status_code=200,
            requested_url=url,
            final_url=url,
            sha256=sha256_bytes(self.payload),
            byte_size=len(self.payload),
            content_type="application/zip",
            content_encoding=None,
            path=Path(destination),
        )


def test_bulk_download_stores_the_archive_and_serves_from_the_store(
    tmp_path: Path,
) -> None:
    import io
    import zipfile as zipfile_module

    from edgar_sec.domain.sec_urls import submissions_bulk_url
    from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
    from edgar_sec.pipelines.metadata_sync.sec_client import (
        SUBMISSIONS_BULK_SOURCE_ID,
        BulkSubmissionsArchive,
    )

    buffer = io.BytesIO()
    with zipfile_module.ZipFile(buffer, "w") as archive:
        for name, payload in _bulk_members().items():
            archive.writestr(name, payload)
    http = _StreamingHttp(buffer.getvalue())
    store = BulkArchiveStore(tmp_path / "store")

    archive = BulkSubmissionsArchive.download(http, store, max_bytes=10_000_000)
    client = BulkSubmissionsClient(archive)
    result = client.fetch_cik(FORD)

    assert result.fetched_ok is True
    assert result.historical_files_fetched == 1
    assert http.calls[0]["url"] == submissions_bulk_url()
    assert http.calls[0]["max_response_bytes"] == 10_000_000
    assert archive.store_reference is not None
    stored = store.open(SUBMISSIONS_BULK_SOURCE_ID)
    assert stored is not None
    assert stored.sha256 == archive.archive_sha256
    assert archive.zip_path == stored.path
    assert not list((tmp_path / "store" / ".downloads").glob("*.zip"))


def test_bulk_download_stream_failure_raises_with_the_failure_detail(
    tmp_path: Path,
) -> None:
    import pytest

    from edgar_sec.infra.sec_http.streaming import StreamFailure
    from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
    from edgar_sec.pipelines.metadata_sync.sec_client import BulkSubmissionsArchive

    class FailingHttp:
        def stream_to_file(self, url, destination, **_kwargs):
            return StreamFailure("http_error", True, 503, "service unavailable")

    store = BulkArchiveStore(tmp_path / "store")
    with pytest.raises(RuntimeError, match="service unavailable"):
        BulkSubmissionsArchive.download(FailingHttp(), store, max_bytes=1024)
    assert store.open("submissions_bulk") is None


def test_bulk_redirect_validator_rejects_leaving_the_bulkdata_directory() -> None:
    import pytest

    from edgar_sec.domain.sec_urls import submissions_bulk_url
    from edgar_sec.pipelines.metadata_sync.sec_client import _validate_bulk_redirect

    _validate_bulk_redirect(submissions_bulk_url())
    with pytest.raises(ValueError):
        _validate_bulk_redirect("https://example.com/Archives/edgar/daily-index/x.zip")
    with pytest.raises(ValueError):
        _validate_bulk_redirect("https://www.sec.gov/Archives/edgar/data/1/x.zip")
