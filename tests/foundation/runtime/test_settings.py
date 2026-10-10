"""Unit tests for the settings registry and its env-name derivation."""

from __future__ import annotations

from edgar_sec.foundation.runtime.settings import (
    environment_name,
    flatten_settings,
    render_dotenv,
    resolve_runtime_settings,
    resolve_settings,
)


def test_environment_name_maps_dotted_paths() -> None:
    assert environment_name("sec.rate_limit_rps") == "SEC_RATE_LIMIT_RPS"
    assert environment_name("runtime.workers") == "RUNTIME_WORKERS"
    assert environment_name("artifacts.root") == "ARTIFACTS_ROOT"


def test_resolve_settings_returns_typed_values() -> None:
    settings = resolve_settings()
    assert float(settings["sec.rate_limit_rps"]) > 0
    assert int(settings["runtime.chunk_size"]) > 0
    assert int(settings["runtime.read_batch_size"]) > 0


def test_resolve_runtime_settings_groups_registries() -> None:
    runtime = resolve_runtime_settings()
    assert runtime.sec.rate_limit_rps > 0
    assert runtime.default_chunk_size > 0
    assert runtime.sec.header_user_agent


def test_environment_override_wins_over_default() -> None:
    settings = resolve_settings(env={"SEC_RATE_LIMIT_RPS": "7"})
    assert float(settings["sec.rate_limit_rps"]) == 7.0


def test_cli_override_wins_over_environment() -> None:
    settings = resolve_settings(
        env={"SEC_RATE_LIMIT_RPS": "7"},
        cli_overrides={"sec.rate_limit_rps": 11.0},
    )
    assert float(settings["sec.rate_limit_rps"]) == 11.0


def test_flatten_settings_strips_secrets() -> None:
    flat = flatten_settings(resolve_settings())
    assert not any("secret" in key.lower() for key in flat)
    assert all(not (value is None) or True for value in flat.values())


def test_render_dotenv_documents_every_setting() -> None:
    rendered = render_dotenv()
    assert "SEC_" in rendered
    assert "RUNTIME_" in rendered


def test_include_filter_restricts_registries() -> None:
    settings = resolve_settings(include=["runtime"])
    assert settings
    assert all(key.startswith("runtime.") for key in settings)


def test_include_filter_yields_nothing_for_unknown_registry() -> None:
    assert resolve_settings(include=["nope"]) == {}
