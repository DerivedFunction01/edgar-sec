import json
from pathlib import Path

from conftest import imp

run_mod = imp("phases.01_metadata_extraction.run")
operator_mod = imp("phases.01_metadata_extraction.operator")
checkpoints = imp("phases.01_metadata_extraction.core.checkpoints")
config = imp("phases.01_metadata_extraction.core.config")
application = imp("phases.01_metadata_extraction.core.application")
source_registry = imp("phases.01_metadata_extraction.core.source_registry")
artifacts_mod = imp("defs.runtime.artifacts")
paths_mod = imp("defs.runtime.paths")
paths_core = imp("phases.01_metadata_extraction.core.paths")

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
    )
    command = operator_mod.partition_command(options, 7)
    assert "--partition-id 7" in command
    assert "--artifacts '.artifacts/metadata/runs/r1'" in command
    assert "--threads" in command
    assert "--user-agent" not in command


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
                user_agent="TestClient/1.0 test@example.com",
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
                user_agent="TestClient/1.0 test@example.com",
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
                user_agent="TestClient/1.0 test@example.com",
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
            storage_format="parquet",
        ),
    )

    options = config.load_project_config(str(config_path)).to_run_options(
        input_path=str(input_csv),
        artifacts_dir=str(artifacts),
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
        artifacts.parent
        / "manifests"
        / "metadata"
        / "submission_metadata"
        / "partitions"
        / "partition-00001"
        / "submission_metadata.parquet"
    )
    assert partition_artifact.exists()
    final_output = (
        artifacts.parent
        / "manifests"
        / "metadata"
        / "submission_metadata"
        / "final"
        / "submission_metadata.parquet"
    )
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
                user_agent="TestClient/1.0 test@example.com",
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
        ),
    )
    options = config.load_project_config(str(config_path)).to_run_options(
        input_path=str(input_csv),
        artifacts_dir=str(artifacts),
    )
    application.build_plan(options)
    application.run_chunk(
        config.RunOptions(**{**options.to_dict(), "chunk_id": 1, "partition_id": 1})
    )

    real_tqdm = operator_mod.tqdm
    monkeypatch.setattr(operator_mod, "tqdm", RecordingBar)
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
    assert (
        artifacts.parent
        / "manifests"
        / "metadata"
        / "submission_metadata"
        / "final"
        / "submission_metadata.parquet"
    ).exists()
    del real_tqdm


def test_interactive_wizard_preview_menu(tmp_path, monkeypatch):
    """The preview menu action must run without NameError and exit cleanly."""
    config_path, _artifacts = _write_wizard_config(tmp_path, FakeSession(), monkeypatch)
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
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
    assert (
        tmp_path / "transient" / "metadata" / "preview" / "preview_summary.json"
    ).exists()


def test_invalid_sec_identity_fails_at_client_build(tmp_path, monkeypatch):
    """SEC identity is owned by shared settings; an invalid value fails clearly."""
    config_path, _ = _write_wizard_config(tmp_path, FakeSession(), monkeypatch)
    fetch = imp("phases.01_metadata_extraction.core.fetch")
    monkeypatch.setenv("SEC_USER_AGENT", "badagent-without-email")
    with pytest.raises(ValueError, match="SEC contact identity is required"):
        fetch.build_client(
            config.RunOptions(
                input_path="uploads/cik-sec.csv",
                artifacts_dir=str(tmp_path / "run"),
            )
        )
    assert config_path.exists()


class _FakeSourceClient:
    def __init__(self, payload: bytes):
        self.payload = payload

    def get_bytes(self, _url: str) -> bytes:
        return self.payload


def _prepare_base_and_source(tmp_path, monkeypatch) -> tuple[str, str]:
    """Complete a fresh CIK-20 base run and publish a two-CIK source snapshot."""
    session = FakeSession()
    session.payloads["https://data.sec.gov/submissions/CIK0000000020.json"] = {
        "cik": "0000000020",
        "name": "K TRON",
        "filings": {"recent": {}, "files": []},
    }

    def fake_build(options):
        from defs import sec_http

        return imp("phases.01_metadata_extraction.core.sec_client").SubmissionsClient(
            http=sec_http.SecHttpClient(
                user_agent="TestClient/1.0 test@example.com",
                rate_limiter=sec_http.RateLimiter(min_interval_s=0.001),
                retry_policy=sec_http.RetryPolicy(
                    max_retries=1, backoff_base_s=0.001, jitter=0.0
                ),
                timeout_s=1.0,
                session_factory=lambda: session,
            )
        )

    monkeypatch.setattr(application, "_build_client", fake_build)

    input_csv = tmp_path / "input.csv"
    input_csv.write_text("cik,name\n20,K Tron\n1761,Tranzonic\n", encoding="utf-8")
    base_input = tmp_path / "base_input.csv"
    base_input.write_text("cik,name\n20,K Tron\n", encoding="utf-8")
    base_dir = tmp_path / "base"
    options = config.RunOptions(
        input_path=str(base_input),
        artifacts_dir=str(base_dir),
        chunk_size=2,
        partition_count=1,
        storage_format="parquet",
    )
    application.build_plan(options)
    application.run_chunk(
        config.RunOptions(**{**options.to_dict(), "chunk_id": 1, "partition_id": 1})
    )
    application.merge_one_partition(options, 1)
    base_report = application.merge(options)

    source = source_registry.refresh_company_tickers(
        artifacts_root=tmp_path,
        client=_FakeSourceClient(
            json.dumps(
                {
                    "0": {"cik_str": 20, "ticker": "KTRO", "title": "K TRON"},
                    "1": {"cik_str": 1761, "ticker": "TRZ", "title": "TRANZONIC"},
                },
                separators=(",", ":"),
            ).encode("utf-8")
        ),
    )
    source_manifest_path = paths_core.resolve_metadata_paths(
        env={"ARTIFACTS_ROOT": str(tmp_path)}
    ).source_manifest_path("company_tickers", source["snapshot_id"])
    manifests = artifacts_mod.find_manifests(
        "submission_metadata", phase="metadata", artifacts_root=str(tmp_path)
    )
    base_manifest = next(
        item
        for item in manifests
        if item["artifact_sha256"] == base_report.artifact_sha256
    )
    base_manifest_path = tmp_path / artifacts_mod.manifest_relative_path(
        phase="metadata",
        dataset="submission_metadata",
        artifact_id_value=base_manifest["artifact_id"],
    )
    return str(source_manifest_path), str(base_manifest_path)


def _write_augment_config(config_path: Path, artifacts_dir: Path, input_csv: Path):
    run_mod.write_project_config(
        str(config_path),
        config.ProjectConfig(
            input_path=str(input_csv),
            artifacts_dir=str(artifacts_dir),
            chunk_size=2,
            partition_count=1,
            storage_format="parquet",
        ),
    )


def test_wizard_prepares_augmentation_from_empty_run(tmp_path, monkeypatch):
    """At the plan prompt, [a] discovers source/base manifests and builds a
    delta-only augmentation plan in an empty run directory."""
    source_manifest, base_manifest = _prepare_base_and_source(tmp_path, monkeypatch)
    assert Path(source_manifest).is_file()
    assert Path(base_manifest).is_file()

    config_path = tmp_path / "config.json"
    augment_dir = tmp_path / "augment"
    _write_augment_config(config_path, augment_dir, tmp_path / "input.csv")

    answers = iter(
        [
            "a",  # no valid plan: create augmentation plan
            "1",  # source snapshot (latest)
            "1",  # base metadata manifest
            "0",  # menu: exit
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    exit_code = run_mod.main(["--config", str(config_path)])
    assert exit_code == 0

    plan = json.loads((augment_dir / "plan.json").read_text(encoding="utf-8"))
    assert plan["augmentation"] is True
    assert plan["row_count"] == 1
    assert plan["cik_padded"] == ["0000001761"]
    assert (tmp_path / plan["worklist_path"]).is_file()
    assert plan["source_manifest"] == source_manifest
    assert plan["base_metadata_manifest"] == base_manifest


def test_wizard_menu_converts_existing_run_to_augmentation(tmp_path, monkeypatch):
    """Menu item [a] converts a completed fresh run's plan into an augmentation
    plan after explicit confirmation, leaving the finalized base artifact alone."""
    source_manifest, base_manifest = _prepare_base_and_source(tmp_path, monkeypatch)

    config_path = tmp_path / "config.json"
    run_dir = tmp_path / "base"
    _write_augment_config(config_path, run_dir, tmp_path / "input.csv")

    answers = iter(
        [
            "y",  # input CSV changed since the fresh plan: regenerate it
            "a",  # menu: prepare augmentation
            "1",  # source snapshot (latest)
            "1",  # base metadata manifest
            "y",  # confirm regeneration as augmentation plan
            "0",  # menu: exit
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    exit_code = run_mod.main(["--config", str(config_path)])
    assert exit_code == 0

    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    assert plan["augmentation"] is True
    assert plan["row_count"] == 1
    assert plan["cik_padded"] == ["0000001761"]
    assert plan["source_manifest"] == source_manifest
    assert plan["base_metadata_manifest"] == base_manifest
    final_manifests = artifacts_mod.find_manifests(
        "submission_metadata", phase="metadata", artifacts_root=str(tmp_path)
    )
    assert len(final_manifests) == 1


def test_wizard_adopts_existing_augmentation_plan_without_flags(tmp_path, monkeypatch):
    """Hands-free resume: launching the wizard with no flags on a run directory
    that already holds an augmentation plan adopts its identity and loads it
    without rewriting anything."""
    source_manifest, base_manifest = _prepare_base_and_source(tmp_path, monkeypatch)
    augment_dir = tmp_path / "augment"
    options = config.RunOptions(
        input_path=str(tmp_path / "input.csv"),
        artifacts_dir=str(augment_dir),
        chunk_size=2,
        partition_count=1,
        storage_format="parquet",
        source_manifest=source_manifest,
        base_metadata_manifest=base_manifest,
        augmentation=True,
    )
    plan = application.build_plan(options)

    config_path = tmp_path / "config.json"
    _write_augment_config(config_path, augment_dir, tmp_path / "input.csv")
    monkeypatch.setattr("builtins.input", lambda prompt="": next(iter(["0"])))
    exit_code = run_mod.main(["--config", str(config_path)])
    assert exit_code == 0

    plan_after = json.loads((augment_dir / "plan.json").read_text(encoding="utf-8"))
    assert plan_after["plan_hash"] == plan["plan_hash"]
    assert plan_after["augmentation"] is True
    assert plan_after["row_count"] == 1


def test_wizard_mismatch_with_explicit_flags_requires_confirmation(
    tmp_path, monkeypatch
):
    """A fresh plan plus pre-seeded augmentation flags is an identity mismatch:
    the rejection is printed and regeneration requires an explicit yes."""
    source_manifest, base_manifest = _prepare_base_and_source(tmp_path, monkeypatch)
    run_dir = tmp_path / "base"

    config_path = tmp_path / "config.json"
    _write_augment_config(config_path, run_dir, tmp_path / "input.csv")

    # First pass: refuse regeneration; the fresh plan must survive untouched.
    answers = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    with pytest.raises(SystemExit):
        run_mod.main(
            [
                "--config",
                str(config_path),
                "--augmentation",
                "--source-manifest",
                source_manifest,
                "--base-metadata-manifest",
                base_manifest,
            ]
        )
    plan_before = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    assert plan_before["augmentation"] is False

    # Second pass: confirm; the plan is regenerated as an augmentation plan.
    answers = iter(["y", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    exit_code = run_mod.main(
        [
            "--config",
            str(config_path),
            "--augmentation",
            "--source-manifest",
            source_manifest,
            "--base-metadata-manifest",
            base_manifest,
        ]
    )
    assert exit_code == 0
    plan_after = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    assert plan_after["augmentation"] is True
    assert plan_after["row_count"] == 1
