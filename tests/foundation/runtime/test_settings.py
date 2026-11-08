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


def test_acquisition_response_limit_defaults_to_256_mib() -> None:
    settings = resolve_settings(include=["acquisition"])
    assert settings["acquisition.max_response_bytes"] == 268435456


def test_acquisition_response_limit_parses_environment() -> None:
    settings = resolve_settings(env={"ACQUISITION_MAX_RESPONSE_BYTES": "4096"})
    assert settings["acquisition.max_response_bytes"] == 4096


def test_acquisition_response_limit_rejects_invalid_environment_values() -> None:
    for value in ("not-an-int", "0", "-1"):
        try:
            resolve_settings(env={"ACQUISITION_MAX_RESPONSE_BYTES": value})
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid response limit {value!r}")


def test_acquisition_response_limit_cli_override_wins() -> None:
    settings = resolve_settings(
        config={"acquisition.max_response_bytes": 2048},
        env={"ACQUISITION_MAX_RESPONSE_BYTES": "4096"},
        cli_overrides={"acquisition.max_response_bytes": 8192},
    )
    assert settings["acquisition.max_response_bytes"] == 8192


def test_acquisition_response_limit_uses_config_fallback() -> None:
    settings = resolve_settings(
        config={"acquisition.max_response_bytes": 16384},
        env={},
    )
    assert settings["acquisition.max_response_bytes"] == 16384


def test_render_dotenv_includes_acquisition_response_limit() -> None:
    rendered = render_dotenv()
    assert "ACQUISITION_MAX_RESPONSE_BYTES=268435456" in rendered


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


def test_surface_policy_census_matches_the_domain_surface_set() -> None:
    from edgar_sec.domain.sec_urls import SEC_SURFACES
    from edgar_sec.foundation.runtime.settings import (
        resolve_no_store_surfaces,
        resolve_surface_ttls,
    )
    from edgar_sec.foundation.runtime.settings.sec import (
        SURFACE_KIND_NO_STORE,
        SURFACE_KIND_STATIC,
        SURFACE_KIND_TRANSIENT,
        SURFACE_POLICIES,
    )

    assert set(SURFACE_POLICIES) == set(SEC_SURFACES)
    assert len(SURFACE_POLICIES) == 30
    kinds = {policy.kind for policy in SURFACE_POLICIES.values()}
    assert kinds == {
        SURFACE_KIND_STATIC,
        SURFACE_KIND_TRANSIENT,
        SURFACE_KIND_NO_STORE,
    }
    assert resolve_no_store_surfaces() == frozenset({"current_filings", "efts"})
    table = resolve_surface_ttls()
    for surface_id, policy in SURFACE_POLICIES.items():
        if policy.kind == SURFACE_KIND_STATIC:
            assert table[surface_id] is None
        elif policy.kind == SURFACE_KIND_NO_STORE:
            assert surface_id not in table
            assert policy.ttl_path is None
        elif surface_id == "structured_disclosure_feeds":
            assert table[surface_id] == 300
            assert table[surface_id] < 600
        else:
            assert table[surface_id] == 24 * 60 * 60


def test_surface_ttl_environment_override() -> None:
    from edgar_sec.foundation.runtime.settings import resolve_surface_ttl_s

    assert (
        resolve_surface_ttl_s("company_tickers", env={"SEC_TTL_COMPANY_TICKERS": "60"})
        == 60
    )
    assert resolve_surface_ttl_s("archive_documents") is None
    assert resolve_surface_ttl_s("no_such_surface") is None


def test_a_transient_policy_without_a_ttl_path_inherits_the_default() -> None:
    import edgar_sec.foundation.runtime.settings as settings_pkg
    from edgar_sec.foundation.runtime.settings.sec import (
        SURFACE_KIND_TRANSIENT,
        SurfacePolicy,
    )

    policies = dict(settings_pkg.SURFACE_POLICIES)
    policies["synthetic_surface"] = SurfacePolicy(
        "synthetic_surface", SURFACE_KIND_TRANSIENT, "test cadence"
    )
    original = settings_pkg.SURFACE_POLICIES
    settings_pkg.SURFACE_POLICIES = policies
    try:
        table = settings_pkg.resolve_surface_ttls(env={"SEC_TTL_DEFAULT_S": "123"})
        assert table["synthetic_surface"] == 123
    finally:
        settings_pkg.SURFACE_POLICIES = original


def test_bulk_archive_retention_setting_defaults_and_env() -> None:
    settings = resolve_settings(include=["sec.bulk_archive"])
    assert settings["sec.bulk_archive.retention"] == 2
    overridden = resolve_settings(env={"SEC_BULK_ARCHIVE_RETENTION": "7"})
    assert overridden["sec.bulk_archive.retention"] == 7
    runtime = resolve_runtime_settings(env={"SEC_BULK_ARCHIVE_RETENTION": "3"})
    assert runtime.sec.bulk_archive_retention == 3


def test_content_cache_fraction_defaults_and_env() -> None:
    settings = resolve_settings(include=["client"])
    assert settings["client.content_cache_fraction"] == 0.25
    assert settings["client.content_disk_budget_bytes"] == 2 * 1024 * 1024 * 1024
    overridden = resolve_settings(env={"CLIENT_CONTENT_CACHE_FRACTION": "0.5"})
    assert overridden["client.content_cache_fraction"] == 0.5
    overridden = resolve_settings(env={"CLIENT_CONTENT_DISK_BUDGET_BYTES": "4096"})
    assert overridden["client.content_disk_budget_bytes"] == 4096
