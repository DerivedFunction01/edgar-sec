from defs.runtime.env import get_env, load_dotenv


def test_load_dotenv_parses_quotes_comments_and_export(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n"
        "# comment line\n"
        "PLAIN=value\n"
        'QUOTED="quoted value"\n'
        "SINGLE='single value'\n"
        "export EXPORTED=exported\n"
        "EMPTY=\n"
        "IGNORED_NO_EQUALS\n",
        encoding="utf-8",
    )
    values = load_dotenv(env_file)
    assert values["PLAIN"] == "value"
    assert values["QUOTED"] == "quoted value"
    assert values["SINGLE"] == "single value"
    assert values["EXPORTED"] == "exported"
    assert values["EMPTY"] == ""
    assert "IGNORED_NO_EQUALS" not in values


def test_load_dotenv_missing_file_returns_empty(tmp_path):
    assert load_dotenv(tmp_path / "missing.env") == {}


def test_get_env_prefers_direct_environment_over_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SEC_TEST_VAR=from_file\n", encoding="utf-8")
    monkeypatch.setenv("SEC_TEST_VAR", "from_environment")
    assert get_env("SEC_TEST_VAR", path=env_file) == "from_environment"


def test_get_env_falls_back_to_dotenv_when_env_unset(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SEC_TEST_VAR=from_file\n", encoding="utf-8")
    monkeypatch.delenv("SEC_TEST_VAR", raising=False)
    assert get_env("SEC_TEST_VAR", path=env_file) == "from_file"


def test_get_env_empty_environment_value_treated_as_unset(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SEC_TEST_VAR=from_file\n", encoding="utf-8")
    monkeypatch.setenv("SEC_TEST_VAR", "")
    assert get_env("SEC_TEST_VAR", path=env_file) == "from_file"


def test_get_env_missing_everywhere_returns_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SEC_TEST_VAR", raising=False)
    assert (
        get_env("SEC_TEST_VAR", "fallback", path=tmp_path / "missing.env") == "fallback"
    )


def test_get_env_uses_edgar_dotenv_path_override(tmp_path, monkeypatch):
    env_file = tmp_path / "custom.env"
    env_file.write_text("SEC_TEST_VAR=custom\n", encoding="utf-8")
    monkeypatch.delenv("SEC_TEST_VAR", raising=False)
    monkeypatch.setenv("EDGAR_DOTENV_PATH", str(env_file))
    assert get_env("SEC_TEST_VAR") == "custom"
