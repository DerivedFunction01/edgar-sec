import json

from conftest import imp

application = imp("phases.01_metadata_extraction.core.application")
checkpoints = imp("phases.01_metadata_extraction.core.checkpoints")
config = imp("phases.01_metadata_extraction.core.config")
schemas = imp("phases.01_metadata_extraction.core.schemas")

import pytest


class FakeResponse:
    def __init__(self, status_code=200, content=b"{}", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class FakeSession:
    def __init__(self):
        self.payloads = {}
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        item = self.payloads.get(url)
        if item is None:
            return FakeResponse(404, b"not found")
        return FakeResponse(200, json.dumps(item).encode("utf-8"))


@pytest.fixture()
def fake_sec(monkeypatch):
    """Patch SubmissionsClient's HTTP construction to use FakeSession."""
    session = FakeSession()

    def register(url, payload):
        session.payloads[url] = payload

    def fake_build(options):
        from defs import sec_http

        # build client with injected session
        client = imp("phases.01_metadata_extraction.core.sec_client").SubmissionsClient(
            http=sec_http.SecHttpClient(
                user_agent=options.user_agent or "TestClient/1.0 test@example.com",
                rate_limiter=sec_http.RateLimiter(min_interval_s=0.001),
                retry_policy=sec_http.RetryPolicy(
                    max_retries=1, backoff_base_s=0.001, jitter=0.0
                ),
                timeout_s=1.0,
                session_factory=lambda: session,
            )
        )
        return client

    monkeypatch.setattr(application, "_build_client", fake_build)
    return session, register


def make_options(tmp_path, **kw):
    defaults = {
        "input_path": str(tmp_path / "input.csv"),
        "artifacts_dir": str(tmp_path / "run"),
        "chunk_size": 2,
        "user_agent": "TestClient/1.0 test@example.com",
    }
    defaults.update(kw)
    options = config.RunOptions(**defaults)
    return options


def write_input(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text(
        "cik,name\n37996,FORD MOTOR CO\n20,K Tron\n1761,Tranzonic\n", encoding="utf-8"
    )
    return str(path)


def test_plan_writes_manifest_without_network(tmp_path):
    input_path = write_input(tmp_path)
    options = make_options(tmp_path, input_path=input_path)
    plan = application.build_plan(options)
    assert plan["row_count"] == 3
    assert plan["chunk_size"] == 2
    assert [c["chunk_id"] for c in plan["chunks"]] == [1, 2]
    assert plan["cik_padded"] == ["0000000020", "0000001761", "0000037996"]
    assert (tmp_path / "run" / "plan.json").exists()


def test_run_chunk_end_to_end_with_fake_http(tmp_path, fake_sec):
    session, register = fake_sec
    base = "https://data.sec.gov/submissions"
    register(
        f"{base}/CIK0000037996.json",
        {
            "cik": "0000037996",
            "name": "FORD MOTOR CO",
            "tickers": ["F"],
            "exchanges": ["NYSE"],
            "filings": {
                "recent": {
                    "accessionNumber": ["0000037996-26-000039"],
                    "filingDate": ["2026-02-05"],
                    "reportDate": ["2025-12-31"],
                    "acceptanceDateTime": ["2026-02-05T18:04:21.431Z"],
                    "act": ["34"],
                    "form": ["10-K"],
                    "fileNumber": ["001-00405"],
                    "filmNumber": ["26551234"],
                    "items": ["10-K"],
                    "core_type": [None],
                    "size": [3380161],
                    "isXBRL": [1],
                    "isInlineXBRL": [1],
                    "isXBRLNumeric": [0],
                    "primaryDocument": ["f-20251231.htm"],
                    "primaryDocDescription": ["10-K"],
                },
                "files": [
                    {
                        "name": "CIK0000037996-submissions-001.json",
                        "FilingCount": 1,
                        "FilingFrom": "2008-01-03",
                        "FilingTo": "2008-01-03",
                    }
                ],
            },
        },
    )
    register(
        f"{base}/CIK0000037996-submissions-001.json",
        {
            "accessionNumber": ["0000037996-08-000010"],
            "filingDate": ["2008-01-03"],
            "reportDate": ["2007-09-30"],
            "acceptanceDateTime": ["2008-01-03T18:30:02.000Z"],
            "act": ["34"],
            "form": ["10-Q"],
            "fileNumber": ["001-00405"],
            "filmNumber": ["08511234"],
            "items": ["10-Q"],
            "core_type": [None],
            "size": [512000],
            "isXBRL": [0],
            "isInlineXBRL": [0],
            "isXBRLNumeric": [0],
            "primaryDocument": ["f12345678_10q.htm"],
            "primaryDocDescription": ["10-Q"],
        },
    )
    register(
        f"{base}/CIK0000000020.json",
        {
            "cik": "0000000020",
            "name": "ACCEL ENTERTAINMENT",
            "filings": {"recent": {}, "files": []},
        },
    )
    register(
        f"{base}/CIK0000001761.json",
        {
            "cik": "0000001761",
            "name": "TRANZONIC",
            "filings": {"recent": {}, "files": []},
        },
    )

    input_path = write_input(tmp_path)
    options = make_options(tmp_path, input_path=input_path)
    application.build_plan(options)

    summary = application.run_chunk(
        config.RunOptions(
            **{**options.to_dict(), "chunk_id": 1, "user_agent": options.user_agent}
        )
    )
    assert summary["rows"] == 2
    assert summary["statuses"] == {"ok": 2}

    # chunk 2 holds the single remaining CIK (Ford) with recent + one historical file
    summary2 = application.run_chunk(
        config.RunOptions(
            **{**options.to_dict(), "chunk_id": 2, "user_agent": options.user_agent}
        )
    )
    assert summary2["statuses"] == {"ok": 1}
    assert summary2["filings"] == 2  # 1 recent + 1 historical

    status = application.get_status(options)
    assert status["completed_chunks"] == 2
    assert status["missing_chunks"] == []
    assert status["mergeable"] is True
    assert status["rows_total"] == 3

    # resume: rerunning a completed chunk is a no-op
    skipped = application.run_chunk(
        config.RunOptions(
            **{**options.to_dict(), "chunk_id": 1, "user_agent": options.user_agent}
        )
    )
    assert skipped["skipped"] is True
    assert len(session.calls) == 4  # no new HTTP requests

    output = tmp_path / "merged.parquet"
    report = application.merge(options, str(output))
    assert report.row_count == 3
    assert report.filing_record_count == 2  # Ford: 1 recent + 1 historical; others: 0


def test_run_chunk_rejects_chunk_id_outside_plan(tmp_path, fake_sec):
    input_path = write_input(tmp_path)
    options = make_options(tmp_path, input_path=input_path)
    application.build_plan(options)
    with pytest.raises(Exception):  # noqa: B017
        application.run_chunk(
            config.RunOptions(
                **{
                    **options.to_dict(),
                    "chunk_id": 99,
                    "user_agent": options.user_agent,
                }
            )
        )


def test_run_chunk_rejects_modified_input(tmp_path, fake_sec):
    input_path = write_input(tmp_path)
    options = make_options(tmp_path, input_path=input_path)
    application.build_plan(options)
    input_path = write_input(tmp_path)  # unchanged; then mutate
    with open(input_path, "a", encoding="utf-8") as fh:
        fh.write("1,Newco\n")
    with pytest.raises(ValueError, match="fingerprint"):
        application.run_chunk(
            config.RunOptions(
                **{**options.to_dict(), "chunk_id": 1, "user_agent": options.user_agent}
            )
        )


def test_jsonl_storage_end_to_end(tmp_path, fake_sec):
    """plan/run/status/merge with JSONL checkpoints through the same harness."""
    session, register = fake_sec
    base = "https://data.sec.gov/submissions"
    register(
        f"{base}/CIK0000037996.json",
        {
            "cik": "0000037996",
            "name": "FORD MOTOR CO",
            "filings": {"recent": {}, "files": []},
        },
    )
    register(
        f"{base}/CIK0000000020.json",
        {
            "cik": "0000000020",
            "name": "ACCEL ENTERTAINMENT",
            "filings": {"recent": {}, "files": []},
        },
    )
    register(
        f"{base}/CIK0000001761.json",
        {
            "cik": "0000001761",
            "name": "TRANZONIC",
            "filings": {"recent": {}, "files": []},
        },
    )

    input_path = write_input(tmp_path)
    options = make_options(tmp_path, input_path=input_path, storage_format="jsonl")
    plan = application.build_plan(options)
    assert plan["storage_format"] == "jsonl"

    summary = application.run_chunk(
        config.RunOptions(
            **{**options.to_dict(), "chunk_id": 1, "user_agent": options.user_agent}
        )
    )
    assert summary["rows"] == 2
    summary2 = application.run_chunk(
        config.RunOptions(
            **{**options.to_dict(), "chunk_id": 2, "user_agent": options.user_agent}
        )
    )
    assert summary2["rows"] == 1

    status = application.get_status(options)
    assert status["completed_chunks"] == 2
    assert status["mergeable"] is True

    output = tmp_path / "merged.parquet"
    report = application.merge(options, str(output))
    assert report.row_count == 3
    assert output.exists()


def test_run_chunk_emits_progress_events(tmp_path, fake_sec):
    session, register = fake_sec
    base = "https://data.sec.gov/submissions"
    register(
        f"{base}/CIK0000000020.json",
        {"cik": "0000000020", "name": "K TRON", "filings": {"recent": {}, "files": []}},
    )
    register(
        f"{base}/CIK0000001761.json",
        {
            "cik": "0000001761",
            "name": "TRANZONIC",
            "filings": {"recent": {}, "files": []},
        },
    )

    input_path = write_input(tmp_path)
    options = make_options(tmp_path, input_path=input_path)
    application.build_plan(options)

    events = []
    summary = application.run_chunk(
        config.RunOptions(
            **{**options.to_dict(), "chunk_id": 1, "user_agent": options.user_agent}
        ),
        progress=events.append,
    )
    assert summary["rows"] == 2
    assert [event["type"] for event in events] == ["cik_done", "cik_done"]
    assert {event["cik"] for event in events} == {"0000000020", "0000001761"}
    for event in events:
        assert event["chunk_id"] == 1
        assert event["status"] == "ok"
        assert event["filings"] == 0
        assert event["historical_files"] == 0
        assert event["metrics"]["requests_total"] >= 1


def test_run_chunk_progress_callback_failure_does_not_break_run(tmp_path, fake_sec):
    session, register = fake_sec
    base = "https://data.sec.gov/submissions"
    register(
        f"{base}/CIK0000000020.json",
        {"cik": "0000000020", "name": "K TRON", "filings": {"recent": {}, "files": []}},
    )
    register(
        f"{base}/CIK0000001761.json",
        {
            "cik": "0000001761",
            "name": "TRANZONIC",
            "filings": {"recent": {}, "files": []},
        },
    )

    input_path = write_input(tmp_path)
    options = make_options(tmp_path, input_path=input_path)
    application.build_plan(options)

    def bad_callback(event):
        raise RuntimeError("callback exploded")

    summary = application.run_chunk(
        config.RunOptions(
            **{**options.to_dict(), "chunk_id": 1, "user_agent": options.user_agent}
        ),
        progress=bad_callback,
    )
    assert summary["rows"] == 2
    assert summary["statuses"] == {"ok": 2}
