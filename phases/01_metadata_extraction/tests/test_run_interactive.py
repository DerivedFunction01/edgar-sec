import json
import pathlib

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


def test_parse_partition_selection_ranges_and_dedup():
    from defs.runtime.partitions import parse_id_selection

    known = list(range(1, 11))
    assert parse_id_selection("1,3,5-8", known, "partition") == [1, 3, 5, 6, 7, 8]
    assert parse_id_selection("8-6", known, "partition") == [6, 7, 8]
    assert parse_id_selection("2,2,2", known, "partition") == [2]
    with pytest.raises(ValueError):
        parse_id_selection("99", known, "partition")


def test_divide_partitions_among_machines_is_balanced_and_contiguous():
    from defs.runtime.partitions import divide_ids_among_workers

    groups = divide_ids_among_workers(list(range(1, 11)), 3)
    assert [len(g) for g in groups] == [4, 3, 3]
    assert groups[0] == [1, 2, 3, 4]
    assert groups[1] == [5, 6, 7]
    assert groups[2] == [8, 9, 10]
    flattened = sorted(i for g in groups for i in g)
    assert flattened == list(range(1, 11))


def test_divide_with_more_machines_than_chunks():
    from defs.runtime.partitions import divide_ids_among_workers

    groups = divide_ids_among_workers([1, 2], 4)
    assert groups == [[1], [2], [], []]


def test_partition_command_contains_required_flags():
    options = config.RunOptions(
        input_path="uploads/cik-sec.csv",
        artifacts_dir=".artifacts/metadata/runs/r1",
        user_agent="App/1.0 a@b.com",
    )
    command = run_mod.partition_command(options, 7)
    assert "--partition-id 7" in command
    assert "--artifacts '.artifacts/metadata/runs/r1'" in command
    assert "a@b.com" in command


def test_interactive_wizard_end_to_end(tmp_path, monkeypatch):
    """Drive the wizard with scripted answers: load config from disk,
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
                retry_policy=sec_http.RetryPolicy(
                    max_retries=1, backoff_base_s=0.001, jitter=0.0
                ),
                timeout_s=1.0,
                session_factory=lambda: session,
            )
        )

    application = imp("phases.01_metadata_extraction.core.application")
    monkeypatch.setattr(application, "_build_client", fake_build)

    input_csv = tmp_path / "input.csv"
    input_csv.write_text(
        "cik,name\n37996,Ford\n20,K Tron\n1761,Tranzonic\n", encoding="utf-8"
    )
    artifacts = tmp_path / "run"
    config_path = tmp_path / "config.json"

    run_mod.write_project_config(
        str(config_path),
        config.ProjectConfig(
            input_path=str(input_csv),
            artifacts_dir=str(artifacts),
            chunk_size=2,
            workers=2,
            rate_limit_rps=10.0,
            user_agent="TestClient/1.0 test@example.com",
            storage_format="parquet",
        ),
    )

    answers = iter(
        [
            "y",  # create plan? (default y)
            "2",  # menu: run a partition
            "1",  # partition id
            "0",  # menu: exit
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    exit_code = run_mod.main(["--config", str(config_path)])
    assert exit_code == 0
    assert (
        len(
            list(
                (artifacts / "partitions" / "partition-00001" / "chunks").glob(
                    "*.parquet"
                )
            )
        )
        == 2
    )

    status_options = config.load_project_config(str(config_path)).to_run_options(
        input_path=str(input_csv),
        artifacts_dir=str(artifacts),
        user_agent="x@y.com",
    )
    status = application.get_status(status_options, partition_id=1)
    assert status["rows_total"] == 3
    assert status["mergeable"] is True


def _write_wizard_config(tmp_path, session, monkeypatch, **config_kwargs):
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
                retry_policy=sec_http.RetryPolicy(
                    max_retries=1, backoff_base_s=0.001, jitter=0.0
                ),
                timeout_s=1.0,
                session_factory=lambda: session,
            )
        )

    application = imp("phases.01_metadata_extraction.core.application")
    monkeypatch.setattr(application, "_build_client", fake_build)

    input_csv = tmp_path / "input.csv"
    input_csv.write_text(
        "cik,name\n37996,Ford\n20,K Tron\n1761,Tranzonic\n", encoding="utf-8"
    )
    config_kwargs.setdefault("input_path", str(input_csv))
    config_kwargs.setdefault("artifacts_dir", str(tmp_path / "run"))
    config_kwargs.setdefault("chunk_size", 2)
    config_kwargs.setdefault("workers", 2)
    config_kwargs.setdefault("rate_limit_rps", 10.0)
    config_kwargs.setdefault("user_agent", "TestClient/1.0 test@example.com")
    config_kwargs.setdefault("storage_format", "parquet")
    config_path = tmp_path / "config.json"
    run_mod.write_project_config(
        str(config_path), config.ProjectConfig(**config_kwargs)
    )
    return config_path, config_kwargs["artifacts_dir"]


def test_interactive_wizard_merge_menu_end_to_end(tmp_path, monkeypatch):
    """Drive the wizard to merge a partition then the final dataset."""
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

    def fake_build(options):
        from defs import sec_http

        return imp("phases.01_metadata_extraction.core.sec_client").SubmissionsClient(
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

    application = imp("phases.01_metadata_extraction.core.application")
    monkeypatch.setattr(application, "_build_client", fake_build)

    input_csv = tmp_path / "input.csv"
    input_csv.write_text("cik,name\n20,K Tron\n1761,Tranzonic\n", encoding="utf-8")
    artifacts = tmp_path / "run"
    config_path = tmp_path / "config.json"

    run_mod.write_project_config(
        str(config_path),
        config.ProjectConfig(
            input_path=str(input_csv),
            artifacts_dir=str(artifacts),
            chunk_size=2,
            partition_count=1,
            workers=2,
            rate_limit_rps=10.0,
            user_agent="TestClient/1.0 test@example.com",
            storage_format="parquet",
        ),
    )

    options = config.load_project_config(str(config_path)).to_run_options(
        input_path=str(input_csv),
        artifacts_dir=str(artifacts),
        user_agent="TestClient/1.0 test@example.com",
    )
    # Produce the completed partition chunks via the core runner.
    application.build_plan(options)
    application.run_chunk(
        config.RunOptions(**{**options.to_dict(), "chunk_id": 1, "partition_id": 1})
    )

    answers = iter(
        [
            "y",  # create plan? (default y)
            "5",  # menu: merge a partition from its chunks
            "1",  # partition id
            "6",  # menu: merge all partition artifacts into the final dataset
            "0",  # menu: exit
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    exit_code = run_mod.main(["--config", str(config_path)])
    assert exit_code == 0
    partition_artifact = (
        artifacts
        / "partitions"
        / "partition-00001"
        / "merge"
        / "submission_metadata.parquet"
    )
    assert partition_artifact.exists()
    final_output = artifacts / "merge" / "submission_metadata.parquet"
    assert final_output.exists()


def test_interactive_wizard_merge_bars_honor_no_progress(tmp_path, monkeypatch):
    """Merge actions pass workers and disable bars under --no-progress."""
    calls = []

    class RecordingBar:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)
            self.total = kwargs.get("total")

        def update(self, amount):
            pass

        def set_postfix(self, value):
            pass

        def close(self):
            pass

    session = FakeSession()
    base = "https://data.sec.gov/submissions"
    session.payloads[f"{base}/CIK0000000020.json"] = {
        "cik": "0000000020",
        "name": "K TRON",
        "filings": {"recent": {}, "files": []},
    }

    def fake_build(options):
        from defs import sec_http

        return imp("phases.01_metadata_extraction.core.sec_client").SubmissionsClient(
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

    application = imp("phases.01_metadata_extraction.core.application")
    monkeypatch.setattr(application, "_build_client", fake_build)

    input_csv = tmp_path / "input.csv"
    input_csv.write_text("cik,name\n20,K Tron\n", encoding="utf-8")
    artifacts = tmp_path / "run"
    config_path = tmp_path / "config.json"
    run_mod.write_project_config(
        str(config_path),
        config.ProjectConfig(
            input_path=str(input_csv),
            artifacts_dir=str(artifacts),
            chunk_size=2,
            partition_count=1,
            workers=3,
            user_agent="TestClient/1.0 test@example.com",
        ),
    )
    options = config.load_project_config(str(config_path)).to_run_options(
        input_path=str(input_csv),
        artifacts_dir=str(artifacts),
        user_agent="TestClient/1.0 test@example.com",
    )
    application.build_plan(options)
    application.run_chunk(
        config.RunOptions(**{**options.to_dict(), "chunk_id": 1, "partition_id": 1})
    )

    real_tqdm = run_mod.tqdm
    monkeypatch.setattr(run_mod, "tqdm", RecordingBar)
    answers = iter(
        [
            "5",  # menu: merge a partition from its chunks
            "1",  # partition id
            "6",  # menu: final merge
            "0",  # exit
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    exit_code = run_mod.main(["--config", str(config_path), "--no-progress"])
    assert exit_code == 0
    assert len(calls) == 2
    partition_bar, final_bar = calls
    assert partition_bar["unit"] == "stage"
    assert partition_bar["total"] == 3
    assert partition_bar["desc"] == "merge partition 1"
    assert partition_bar["disable"] is True
    assert final_bar["unit"] == "step"
    assert final_bar["total"] == 3  # one partition + publish + readback
    assert final_bar["desc"] == "final merge"
    assert final_bar["disable"] is True
    assert (artifacts / "merge" / "submission_metadata.parquet").exists()
    del real_tqdm


def test_interactive_wizard_preview_menu(tmp_path, monkeypatch):
    """The preview menu action must run without NameError and exit cleanly."""
    config_path, artifacts = _write_wizard_config(tmp_path, FakeSession(), monkeypatch)
    answers = iter(
        [
            "y",  # create plan?
            "1",  # menu: preview
            "0",  # menu: exit
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    exit_code = run_mod.main(["--config", str(config_path)])
    assert exit_code == 0
    assert (pathlib.Path(artifacts) / "preview_summary.json").exists()


def test_interactive_wizard_rejects_missing_sec_identity(tmp_path, monkeypatch):
    """A missing SEC identity exits with a clear error, never a traceback."""
    config_path, _ = _write_wizard_config(
        tmp_path, FakeSession(), monkeypatch, user_agent=""
    )
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.setenv("EDGAR_DOTENV_PATH", str(tmp_path / "missing.env"))
    answers = iter([])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    exit_code = run_mod.main(["--config", str(config_path)])
    assert exit_code == 2
