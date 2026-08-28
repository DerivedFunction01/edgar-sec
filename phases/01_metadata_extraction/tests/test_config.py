import json
import os

from conftest import imp

config_mod = imp("phases.01_metadata_extraction.core.config")
application = imp("phases.01_metadata_extraction.core.application")
run_mod = imp("phases.01_metadata_extraction.run")

import pytest


def test_default_project_config_has_sensible_values():
    cfg = config_mod.default_project_config()
    assert cfg.input_path == "uploads/cik-sec.csv"
    assert cfg.chunk_size == 1000
    assert cfg.storage_format == "parquet"
    assert cfg.workers == 4


def test_write_and_load_project_config_round_trip(tmp_path):
    cfg = config_mod.ProjectConfig(
        input_path="uploads/other.csv",
        artifacts_dir=str(tmp_path / "run"),
        chunk_size=500,
        workers=2,
        timeout_s=30.0,
        max_retries=2,
        rate_limit_rps=2.0,
        user_agent="MyApp/1.0 me@example.com",
        cache_dir=str(tmp_path / "cache"),
        max_failure_attempts=5,
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
    assert loaded.user_agent == config_mod.default_user_agent()
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


def test_load_project_config_rejects_unknown_fields(tmp_path):
    config_path = tmp_path / "bad.json"
    config_path.write_text(
        '{"version": 2, "config": {"unknown_field": 1}}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unknown config fields"):
        config_mod.load_project_config(str(config_path))


def test_load_project_config_rejects_removed_user_agent_env(tmp_path):
    """The obsolete user_agent_env branch is gone; it fails as unknown."""
    config_path = tmp_path / "bad.json"
    config_path.write_text(
        '{"version": 2, "config": {"dataset": {}, '
        '"credentials": {"user_agent_env": "SEC_USER_AGENT"}}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown config fields.*user_agent_env"):
        config_mod.load_project_config(str(config_path))


def test_persisted_config_omits_credentials(tmp_path):
    cfg = config_mod.ProjectConfig(user_agent="App/1.0 a@b.com")
    assert "credentials" not in cfg.to_dict()


def test_load_project_config_rejects_invalid_storage_format(tmp_path):
    config_path = tmp_path / "bad.json"
    config_path.write_text(
        '{"version": 2, "config": {"storage_format": "xml"}}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="storage_format must be"):
        config_mod.load_project_config(str(config_path))


def test_load_project_config_accepts_empty_user_agent(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"version": 2, "config": {"user_agent": ""}}', encoding="utf-8"
    )
    loaded = config_mod.load_project_config(str(config_path))
    assert loaded.user_agent == ""


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


def test_project_config_validate_requires_workers_at_least_one():
    cfg = config_mod.default_project_config()
    cfg.workers = 0
    with pytest.raises(ValueError, match="workers must be >= 1"):
        cfg.validate()


def test_project_config_to_run_options_round_trip():
    cfg = config_mod.ProjectConfig(
        input_path="uploads/cik-sec.csv",
        artifacts_dir=".artifacts/metadata/runs/local",
        chunk_size=1000,
        workers=4,
        timeout_s=15.0,
        max_retries=4,
        rate_limit_rps=4.0,
        user_agent="App/1.0 a@b.com",
        cache_dir="",
        max_failure_attempts=3,
        limit=None,
        storage_format="parquet",
    )
    options = cfg.to_run_options(chunk_id=5, log_level="DEBUG", run_id="test")
    assert options.input_path == cfg.input_path
    assert options.chunk_size == cfg.chunk_size
    assert options.chunk_id == 5
    assert options.log_level == "DEBUG"
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
        user_agent="TestClient/1.0 test@example.com",
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
        user_agent="TestClient/1.0 test@example.com",
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
        user_agent="TestClient/1.0 test@example.com",
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
        user_agent="TestClient/1.0 test@example.com",
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
        user_agent="TestClient/1.0 test@example.com",
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
            "--user-agent",
            "NewApp/1.0 new@example.com",
            "--chunk-size",
            "500",
        ]
    )
    assert exit_code == 0
    assert config_path.exists()
    loaded = config_mod.load_project_config(str(config_path))
    assert loaded.chunk_size == 500
    assert loaded.user_agent == config_mod.default_user_agent()


def test_cli_override_does_not_modify_config_file(tmp_path):
    """Temporary CLI overrides affect RunOptions but leave config.json unchanged."""
    run_mod = imp("phases.01_metadata_extraction.run")
    config_path = tmp_path / "config.json"
    cfg = config_mod.ProjectConfig(
        input_path="uploads/cik-sec.csv",
        artifacts_dir=str(tmp_path / "run"),
        chunk_size=1000,
        workers=4,
        rate_limit_rps=4.0,
        user_agent="App/1.0 a@b.com",
        storage_format="parquet",
    )
    config_mod.write_project_config(str(config_path), cfg)
    original_text = config_path.read_text(encoding="utf-8")

    options = run_mod.options_from_args(
        type(
            "Args",
            (),
            {
                "config": str(config_path),
                "configure": False,
                "input": None,
                "artifacts": None,
                "chunk_size": 500,
                "storage_format": None,
                "chunk_id": None,
                "workers": None,
                "timeout": None,
                "max_retries": None,
                "rate_limit": None,
                "user_agent": None,
                "cache_dir": None,
                "max_failure_attempts": None,
                "ignore_failure_history": False,
                "limit": None,
                "log_level": "INFO",
                "run_id": "local",
                "no_progress": False,
            },
        )(),
        cfg,
    )
    assert options.chunk_size == 500
    assert config_path.read_text(encoding="utf-8") == original_text


def test_empty_config_user_agent_falls_back_to_dotenv(tmp_path, monkeypatch):
    """A config persisted with an empty user agent must not shadow .env."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SEC_USER_AGENT=EnvAgent/1.0 env@example.com\n", encoding="utf-8"
    )
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.setenv("DOTENV_PATH", str(env_file))
    cfg = config_mod.ProjectConfig(
        input_path="uploads/cik-sec.csv",
        artifacts_dir=str(tmp_path / "run"),
        user_agent="",
    )
    args = type(
        "Args",
        (),
        {
            "config": str(tmp_path / "config.json"),
            "configure": False,
            "input": None,
            "artifacts": None,
            "chunk_size": None,
            "storage_format": None,
            "chunk_id": None,
            "workers": None,
            "timeout": None,
            "max_retries": None,
            "rate_limit": None,
            "user_agent": None,
            "cache_dir": None,
            "max_failure_attempts": None,
            "ignore_failure_history": False,
            "limit": None,
            "log_level": "INFO",
            "run_id": "local",
            "no_progress": False,
        },
    )()
    options = run_mod.options_from_args(args, cfg)
    assert options.user_agent == "EnvAgent/1.0 env@example.com"


def test_partition_command_includes_config_path():
    options = config_mod.RunOptions(
        input_path="uploads/cik-sec.csv",
        artifacts_dir=".artifacts/metadata/runs/r1",
        user_agent="App/1.0 a@b.com",
    )
    command = run_mod.partition_command(options, 7)
    assert "--config .artifacts/metadata/config.json" in command


def test_plan_creation_records_run_options_for_jsonl(tmp_path):
    """Plan JSON records run_options for both Parquet and JSONL."""
    input_path = tmp_path / "input.csv"
    input_path.write_text("cik,name\n37996,Ford\n", encoding="utf-8")
    options = config_mod.RunOptions(
        input_path=str(input_path),
        artifacts_dir=str(tmp_path / "run"),
        chunk_size=1,
        user_agent="TestClient/1.0 test@example.com",
        storage_format="jsonl",
    )
    plan = application.build_plan(options)
    assert plan["run_options"]["storage_format"] == "jsonl"
    assert plan["storage_format"] == "jsonl"
