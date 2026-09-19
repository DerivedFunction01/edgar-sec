import json
import os

from conftest import imp

config_mod = imp("phases.01_metadata_extraction.core.config")
application = imp("phases.01_metadata_extraction.core.application")
run_mod = imp("phases.01_metadata_extraction.run")
operator_mod = imp("phases.01_metadata_extraction.operator")

import pytest


def test_default_project_config_has_sensible_values():
    cfg = config_mod.default_project_config()
    assert cfg.input_path == "uploads/cik-sec.csv"
    assert cfg.chunk_size == 1000
    assert cfg.storage_format == "parquet"
    # Concurrency is machine-derived at runtime; the config does not persist it.
    assert "threads" not in cfg.to_dict()["execution"]
    # SEC transport settings are shared, never phase-owned.
    assert "sec_http" not in cfg.to_dict()


def test_write_and_load_project_config_round_trip(tmp_path):
    cfg = config_mod.ProjectConfig(
        input_path="uploads/other.csv",
        artifacts_dir=str(tmp_path / "run"),
        chunk_size=500,
        limit=100,
        storage_format="jsonl",
    )
    config_path = tmp_path / "config.json"
    written = config_mod.write_project_config(str(config_path), cfg)
    assert os.path.exists(written)
    loaded = config_mod.load_project_config(str(config_path))
    assert loaded.input_path == cfg.input_path
    assert loaded.chunk_size == cfg.chunk_size
    assert loaded.storage_format == cfg.storage_format
    assert loaded.limit == cfg.limit


def test_load_project_config_rejects_malformed_json(tmp_path):
    config_path = tmp_path / "bad.json"
    config_path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="config file is not valid JSON"):
        config_mod.load_project_config(str(config_path))


def test_load_project_config_rejects_missing_config_object(tmp_path):
    config_path = tmp_path / "bad.json"
    config_path.write_text('{"version": 2}', encoding="utf-8")
    with pytest.raises(ValueError, match="config file must contain a 'config' object"):
        config_mod.load_project_config(str(config_path))


def test_load_project_config_ignores_unknown_fields(tmp_path):
    config_path = tmp_path / "bad.json"
    config_path.write_text(
        '{"version": 2, "config": {"unknown_field": 1}}', encoding="utf-8"
    )
    loaded = config_mod.load_project_config(str(config_path))
    assert loaded.input_path == "uploads/cik-sec.csv"


def test_load_project_config_ignores_removed_user_agent_env(tmp_path):
    """Obsolete credentials fields are ignored; configs can be regenerated."""
    config_path = tmp_path / "bad.json"
    config_path.write_text(
        '{"version": 2, "config": {"dataset": {}, '
        '"credentials": {"user_agent_env": "SEC_USER_AGENT"}}}',
        encoding="utf-8",
    )
    loaded = config_mod.load_project_config(str(config_path))
    assert loaded.input_path == "uploads/cik-sec.csv"


def test_load_project_config_ignores_legacy_sec_http_sections(tmp_path):
    """SEC transport values were moved to shared settings; old sections are ignored."""
    config_path = tmp_path / "legacy.json"
    config_path.write_text(
        '{"version": 2, "config": {'
        '"dataset": {"input_path": "uploads/cik-sec.csv"},'
        '"execution": {"chunk_size": 250, "workers": 4},'
        '"sec_http": {"timeout_s": 99.0, "user_agent": "Legacy/1.0 legacy@example.com"},'
        '"metadata": {"max_failure_attempts": 9}'
        "}}",
        encoding="utf-8",
    )
    loaded = config_mod.load_project_config(str(config_path))
    assert loaded.chunk_size == 250
    assert not hasattr(loaded, "timeout_s")
    assert not hasattr(loaded, "user_agent")


def test_load_project_config_rejects_invalid_storage_format(tmp_path):
    config_path = tmp_path / "bad.json"
    config_path.write_text(
        '{"version": 2, "config": {"storage_format": "xml"}}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="storage_format must be"):
        config_mod.load_project_config(str(config_path))


def test_load_project_config_rejects_wrong_version(tmp_path):
    config_path = tmp_path / "bad.json"
    config_path.write_text('{"version": 3, "config": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported config version"):
        config_mod.load_project_config(str(config_path))


def test_load_project_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        config_mod.load_project_config(str(tmp_path / "nonexistent.json"))


def test_atomic_write_uses_temp_file_and_rename(tmp_path):
    cfg = config_mod.default_project_config()
    config_path = tmp_path / "config.json"
    config_mod.write_project_config(str(config_path), cfg)
    # The temp file should not exist after successful write
    temp_files = list(tmp_path.glob(".config-*.tmp"))
    assert temp_files == []
    assert config_path.exists()
    with open(config_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["version"] == config_mod.CONFIG_VERSION
    assert "config" in data


def test_project_config_validate_rejects_bad_chunk_size():
    cfg = config_mod.default_project_config()
    cfg.chunk_size = 0
    with pytest.raises(ValueError, match="chunk_size must be >= 1"):
        cfg.validate()


def test_project_config_to_run_options_round_trip():
    cfg = config_mod.ProjectConfig(
        input_path="uploads/cik-sec.csv",
        artifacts_dir=".artifacts/metadata/runs/local",
        chunk_size=1000,
        limit=None,
        storage_format="parquet",
    )
    options = cfg.to_run_options(chunk_id=5, run_id="test")
    assert options.input_path == cfg.input_path
    assert options.chunk_size == cfg.chunk_size
    assert options.chunk_id == 5
    assert options.run_id == "test"


def test_build_plan_records_run_options(tmp_path):
    input_path = tmp_path / "input.csv"
    input_path.write_text(
        "cik,name\n37996,Ford\n20,K Tron\n1761,Tranzonic\n", encoding="utf-8"
    )
    options = config_mod.RunOptions(
        input_path=str(input_path),
        artifacts_dir=str(tmp_path / "run"),
        chunk_size=2,
    )
    plan = application.build_plan(options)
    assert "run_options" in plan
    run_options = plan["run_options"]
    assert run_options["input_path"] == str(input_path)
    assert run_options["chunk_size"] == 2
    assert run_options["storage_format"] == "parquet"
    assert run_options["limit"] is None


def test_validate_plan_against_options_rejects_stale_chunk_size(tmp_path):
    input_path = tmp_path / "input.csv"
    input_path.write_text("cik,name\n37996,Ford\n", encoding="utf-8")
    options = config_mod.RunOptions(
        input_path=str(input_path),
        artifacts_dir=str(tmp_path / "run"),
        chunk_size=1,
    )
    plan = application.build_plan(options)
    # Modify plan to simulate stale config
    plan.pop("plan_hash", None)
    plan["run_options"]["chunk_size"] = 999
    plan_path = tmp_path / "run" / "plan.json"
    with open(plan_path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2, sort_keys=True)
    with pytest.raises(ValueError, match="chunk_size"):
        application.load_plan(options)


def test_validate_plan_against_options_rejects_stale_input_path(tmp_path):
    input_path = tmp_path / "input.csv"
    input_path.write_text("cik,name\n37996,Ford\n", encoding="utf-8")
    options = config_mod.RunOptions(
        input_path=str(input_path),
        artifacts_dir=str(tmp_path / "run"),
        chunk_size=1,
    )
    plan = application.build_plan(options)
    plan.pop("plan_hash", None)
    plan["run_options"]["input_path"] = "uploads/other.csv"
    plan_path = tmp_path / "run" / "plan.json"
    with open(plan_path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2, sort_keys=True)
    with pytest.raises(ValueError, match="input_path"):
        application.load_plan(options)


def test_validate_plan_against_options_rejects_stale_storage_format(tmp_path):
    input_path = tmp_path / "input.csv"
    input_path.write_text("cik,name\n37996,Ford\n", encoding="utf-8")
    options = config_mod.RunOptions(
        input_path=str(input_path),
        artifacts_dir=str(tmp_path / "run"),
        chunk_size=1,
    )
    plan = application.build_plan(options)
    plan.pop("plan_hash", None)
    plan["run_options"]["storage_format"] = "jsonl"
    plan_path = tmp_path / "run" / "plan.json"
    with open(plan_path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2, sort_keys=True)
    with pytest.raises(ValueError, match="storage_format"):
        application.load_plan(options)


def test_validate_plan_against_options_accepts_matching_run_options(tmp_path):
    input_path = tmp_path / "input.csv"
    input_path.write_text("cik,name\n37996,Ford\n", encoding="utf-8")
    options = config_mod.RunOptions(
        input_path=str(input_path),
        artifacts_dir=str(tmp_path / "run"),
        chunk_size=1,
    )
    application.build_plan(options)
    # Loading with matching options should succeed
    plan = application.load_plan(options)
    assert plan["chunk_size"] == 1


def test_run_main_creates_template_on_missing_config(tmp_path, monkeypatch, capsys):
    """First invocation with no config creates a template and exits without network."""
    run_mod = imp("phases.01_metadata_extraction.run")
    config_path = tmp_path / "config.json"
    exit_code = run_mod.main(["--config", str(config_path)])
    assert exit_code == 0
    assert config_path.exists()
    captured = capsys.readouterr()
    assert "Config not found" in captured.out
    assert "Created template at" in captured.out


def test_run_configure_writes_config_and_exits(tmp_path):
    """--configure writes only the config file and exits without network."""
    run_mod = imp("phases.01_metadata_extraction.run")
    config_path = tmp_path / "config.json"
    exit_code = run_mod.main(
        [
            "--config",
            str(config_path),
            "--configure",
            "--chunk-size",
            "500",
            "--limit",
            "100",
        ]
    )
    assert exit_code == 0
    assert config_path.exists()
    loaded = config_mod.load_project_config(str(config_path))
    assert loaded.chunk_size == 500
    assert loaded.limit == 100
    persisted = json.loads(config_path.read_text(encoding="utf-8"))["config"]
    assert "sec_http" not in persisted
    assert "credentials" not in persisted


def test_cli_override_does_not_modify_config_file(tmp_path):
    """Temporary CLI overrides affect RunOptions but leave config.json unchanged."""
    run_mod = imp("phases.01_metadata_extraction.run")
    config_path = tmp_path / "config.json"
    cfg = config_mod.ProjectConfig(
        input_path="uploads/cik-sec.csv",
        artifacts_dir=str(tmp_path / "run"),
        chunk_size=1000,
        storage_format="parquet",
    )
    config_mod.write_project_config(str(config_path), cfg)
    original_text = config_path.read_text(encoding="utf-8")

    options = run_mod.options_from_args(
        _args(chunk_size=500),
        cfg,
    )
    assert options.chunk_size == 500
    assert config_path.read_text(encoding="utf-8") == original_text


def _args(**overrides):
    values = {
        "config": "x",
        "configure": False,
        "input": None,
        "artifacts": None,
        "chunk_size": None,
        "partition_count": None,
        "partition_id": None,
        "storage_format": None,
        "chunk_id": None,
        "threads": None,
        "limit": None,
        "log_level": "INFO",
        "run_id": "local",
        "no_progress": False,
        "source_manifest": None,
        "base_metadata_manifest": None,
        "augmentation": False,
    }
    values.update(overrides)
    return type("Args", (), values)()


def test_partition_command_includes_config_path():
    options = config_mod.RunOptions(
        input_path="uploads/cik-sec.csv",
        artifacts_dir=".artifacts/metadata/runs/r1",
    )
    command = operator_mod.partition_command(options, 7)
    assert "--config .artifacts/metadata/config.json" in command


def test_partition_command_uses_threads_and_omits_sec_flags():
    options = config_mod.RunOptions(
        input_path="uploads/cik-sec.csv",
        artifacts_dir=".artifacts/metadata/runs/r1",
        threads=4,
    )
    command = operator_mod.partition_command(options, 7)
    assert "--threads 4" in command
    assert "--workers" not in command
    assert "--user-agent" not in command
    assert "--rate-limit" not in command


def test_plan_creation_records_run_options_for_jsonl(tmp_path):
    """Plan JSON records run_options for both Parquet and JSONL."""
    input_path = tmp_path / "input.csv"
    input_path.write_text("cik,name\n37996,Ford\n", encoding="utf-8")
    options = config_mod.RunOptions(
        input_path=str(input_path),
        artifacts_dir=str(tmp_path / "run"),
        chunk_size=1,
        storage_format="jsonl",
    )
    plan = application.build_plan(options)
    assert plan["run_options"]["storage_format"] == "jsonl"
    assert plan["storage_format"] == "jsonl"
    assert "user_agent" not in plan["run_options"]


def test_run_options_threads_default_is_unset():
    opts = config_mod.RunOptions(input_path="uploads/cik-sec.csv")
    assert opts.threads is None


def test_effective_threads_honors_explicit_value():
    opts = config_mod.RunOptions(input_path="uploads/cik-sec.csv", threads=3)
    assert opts.effective_threads() == 3


def test_effective_threads_derives_when_unset(monkeypatch):
    from types import SimpleNamespace

    import defs.runtime.resources as res

    monkeypatch.setattr(res, "derive_resources", lambda: SimpleNamespace(threads=1))
    opts = config_mod.RunOptions(input_path="uploads/cik-sec.csv")
    # Unset thread overrides defer to the shared thread resource profile.
    assert opts.effective_threads() == 1


def test_options_from_args_resolves_omitted_threads_to_auto():
    run_mod = imp("phases.01_metadata_extraction.run")
    cfg = config_mod.ProjectConfig(input_path="uploads/cik-sec.csv")
    options = run_mod.options_from_args(_args(threads=None), cfg)
    assert options.effective_threads() >= 1


def test_options_from_args_honors_explicit_threads():
    run_mod = imp("phases.01_metadata_extraction.run")
    cfg = config_mod.ProjectConfig(input_path="uploads/cik-sec.csv")
    options = run_mod.options_from_args(_args(threads=7), cfg)
    assert options.threads == 7


def test_legacy_workers_config_key_is_ignored(tmp_path):
    config_path = tmp_path / "legacy.json"
    config_path.write_text(
        '{"version": 2, "config": {"workers": 4, "chunk_size": 100}}',
        encoding="utf-8",
    )
    loaded = config_mod.load_project_config(str(config_path))
    assert loaded.chunk_size == 100
    assert "workers" not in loaded.to_dict()["execution"]


def test_run_options_to_dict_omits_threads_when_unset():
    opts = config_mod.RunOptions(input_path="uploads/cik-sec.csv")
    assert "threads" not in opts.to_dict()


def test_build_client_resolves_identity_from_shared_settings(tmp_path, monkeypatch):
    """The phase client inherits SEC identity from the shared settings registry."""
    fetch = imp("phases.01_metadata_extraction.core.fetch")
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    client = fetch.build_client(config_mod.RunOptions())
    assert "@" in client.http.headers["User-Agent"]
