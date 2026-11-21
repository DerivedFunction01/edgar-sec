"""Unit tests for foundation.runtime.env."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.env import (
    get_env,
    get_env_bool,
    get_env_float,
    get_env_int,
    load_dotenv,
)

ENV_FILE = """
# Comment line
SEC_USER_AGENT=Test Corp Admin@test.com
CONCURRENCY=8
RATE_LIMIT=3.5
DEBUG_MODE=true
EMPTY_VAR=
QUOTED_VAL="quoted string"
"""


def _env_file(tmp_path: Path) -> Path:
    path = tmp_path / "test.env"
    path.write_text(ENV_FILE, encoding="utf-8")
    return path


def test_load_dotenv_parses_values_and_quotes(tmp_path: Path) -> None:
    parsed = load_dotenv(_env_file(tmp_path))
    assert parsed["SEC_USER_AGENT"] == "Test Corp Admin@test.com"
    assert parsed["QUOTED_VAL"] == "quoted string"


def test_typed_env_accessors(tmp_path: Path) -> None:
    env_file = _env_file(tmp_path)
    assert get_env("SEC_USER_AGENT", dotenv_path=env_file) == "Test Corp Admin@test.com"
    assert get_env_int("CONCURRENCY", default=4, dotenv_path=env_file) == 8
    assert get_env_float("RATE_LIMIT", default=1.0, dotenv_path=env_file) == 3.5
    assert get_env_bool("DEBUG_MODE", default=False, dotenv_path=env_file) is True


def test_missing_and_empty_values_use_defaults(tmp_path: Path) -> None:
    """An empty assignment is treated as unset, so the default wins."""
    env_file = _env_file(tmp_path)
    assert get_env("NOPE", default="fallback", dotenv_path=env_file) == "fallback"
    assert get_env_int("EMPTY_VAR", default=7, dotenv_path=env_file) == 7
    assert get_env("EMPTY_VAR", default="fallback", dotenv_path=env_file) == "fallback"
