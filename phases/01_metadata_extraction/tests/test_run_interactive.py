import json

from conftest import imp

run_mod = imp("phases.01_metadata_extraction.run")
checkpoints = imp("phases.01_metadata_extraction.core.checkpoints")
config = imp("phases.01_metadata_extraction.core.config")

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
        payload = self.payloads.get(url)
        if payload is None:
            return FakeResponse(404, b"not found")
        return FakeResponse(200, json.dumps(payload).encode("utf-8"))


def test_parse_chunk_spec_ranges_and_dedup():
    known = list(range(1, 11))
    assert run_mod.parse_chunk_spec("1,3,5-8", known) == [1, 3, 5, 6, 7, 8]
    assert run_mod.parse_chunk_spec("8-6", known) == [6, 7, 8]
    assert run_mod.parse_chunk_spec("2,2,2", known) == [2]
    with pytest.raises(ValueError):
        run_mod.parse_chunk_spec("99", known)


def test_divide_chunks_among_machines_is_balanced_and_contiguous():
    groups = run_mod.divide_chunks_among_machines(list(range(1, 11)), 3)
    assert [len(g) for g in groups] == [4, 3, 3]
    assert groups[0] == [1, 2, 3, 4]
    assert groups[1] == [5, 6, 7]
    assert groups[2] == [8, 9, 10]
    flattened = sorted(i for g in groups for i in g)
    assert flattened == list(range(1, 11))


def test_divide_with_more_machines_than_chunks():
    groups = run_mod.divide_chunks_among_machines([1, 2], 4)
    assert groups == [[1], [2], [], []]


def test_chunk_command_contains_required_flags():
    options = config.RunOptions(
        input_path="uploads/cik-sec.csv",
        artifacts_dir=".artifacts/metadata/runs/r1",
        user_agent="App/1.0 a@b.com",
        chunk_id=7,
    )
    command = run_mod.chunk_command(options, 7)
    assert "--chunk-id 7" in command
    assert "--artifacts .artifacts/metadata/runs/r1" in command
    assert "a@b.com" in command


def test_interactive_wizard_end_to_end(tmp_path, monkeypatch):
    """Drive the wizard with scripted answers: accept config defaults,
    create the plan, run chunks 1-2 via the 'specific chunks' menu, exit."""
    session = FakeSession()
    base = "https://data.sec.gov/submissions"
    session.payloads[f"{base}/CIK0000000020.json"] = {
        "cik": "0000000020",
        "name": "K TRON",
        "filings": {"recent": {}, "files": []},
    }
    session.payloads[f"{base}/CIK0000001761.json"] = {
        "cik": "0000001761",
        "name": "TRANZONIC",
        "filings": {"recent": {}, "files": []},
    }
    session.payloads[f"{base}/CIK0000037996.json"] = {
        "cik": "0000037996",
        "name": "FORD MOTOR CO",
        "filings": {"recent": {}, "files": []},
    }

    def fake_build(options):
        from defs import sec_http

        return imp("phases.01_metadata_extraction.core.sec_client").SubmissionsClient(
            http=sec_http.SecHttpClient(
                user_agent=options.user_agent or "TestClient/1.0 test@example.com",
                rate_limiter=sec_http.RateLimiter(min_interval_s=0.001),
                retry_policy=sec_http.RetryPolicy(max_retries=1, backoff_base_s=0.001, jitter=0.0),
                timeout_s=1.0,
                session_factory=lambda: session,
            )
        )

    application = imp("phases.01_metadata_extraction.core.application")
    monkeypatch.setattr(application, "_build_client", fake_build)

    input_csv = tmp_path / "input.csv"
    input_csv.write_text("cik,name\n37996,Ford\n20,K Tron\n1761,Tranzonic\n", encoding="utf-8")
    artifacts = tmp_path / "run"

    answers = iter(
        [
            str(input_csv),          # input CSV
            str(artifacts),          # artifacts dir
            "2",                     # chunk size
            "2",                     # workers
            "10",                    # rate limit
            "TestClient/1.0 test@example.com",  # user agent
            "",                      # cache dir (off)
            "",                      # create plan? (default y)
            "3",                     # menu: run specific chunks
            "1-2",                   # chunk spec
            "0",                     # menu: exit
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    exit_code = run_mod.main([])
    assert exit_code == 0
    assert len(list((artifacts / "chunks").glob("*.parquet"))) == 2

    status = application.get_status(
        config.RunOptions(
            input_path=str(input_csv), artifacts_dir=str(artifacts), user_agent="x@y.com"
        )
    )
    assert status["rows_total"] == 3
    assert status["mergeable"] is True
