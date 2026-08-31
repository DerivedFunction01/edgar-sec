"""Contract tests for the typed settings registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from defs.runtime import settings as settings_mod
from defs.runtime.settings import (
    MISSING,
    SettingSpec,
    collect_specs,
    environment_name,
    flatten_settings,
    get_setting,
    render_dotenv,
    resolve_settings,
)
from defs.runtime.settings_cli import generate_dotenv


def _resolve_all(env=None, **kwargs):
    """Full shared resolution; explicit env values keep tests offline."""
    return resolve_settings(env=env, **kwargs)


# --- collection and naming ----------------------------------------------------


def test_shared_specs_collect_with_logical_paths_and_spec_types():
    specs = collect_specs()
    for path in (
        "runtime.workers",
        "runtime.chunk_size",
        "runtime.partition_count",
        "runtime.threads",
        "runtime.memory_limit",
        "runtime.memory_fraction",
        "runtime.temp_directory",
        "artifacts.root",
        "cache.root",
        "sec.user_agent",
        "sec.rate_limit_rps",
        "sec.timeout_s",
        "sec.max_retries",
        "sec.max_failure_attempts",
    ):
        assert isinstance(specs[path], SettingSpec), path


def test_recursive_collection_nests_groups_into_dotted_paths():
    specs: dict[str, SettingSpec] = {}
    settings_mod._flatten_group(
        {"group": {"outer": {"inner": SettingSpec(default=1)}}}, "", specs
    )
    assert set(specs) == {"group.outer.inner"}


def test_duplicate_setting_paths_are_rejected():
    specs: dict[str, SettingSpec] = {}
    settings_mod._flatten_group({"group": {"x": SettingSpec(default=1)}}, "", specs)
    with pytest.raises(ValueError, match="duplicate setting path 'group.x'"):
        settings_mod._flatten_group({"group": {"x": SettingSpec(default=2)}}, "", specs)


def test_malformed_spec_tree_is_rejected():
    with pytest.raises(ValueError, match="malformed setting spec at 'group.x'"):
        settings_mod._flatten_group({"group": {"x": "not-a-spec"}}, "", {})


def test_invalid_setting_names_are_rejected():
    with pytest.raises(ValueError, match="invalid setting name"):
        settings_mod._flatten_group({"group": {"BAD-NAME": SettingSpec()}}, "", {})


@pytest.mark.parametrize(
    ("logical", "expected"),
    [
        ("runtime.threads", "RUNTIME_THREADS"),
        ("runtime.memory_limit", "RUNTIME_MEMORY_LIMIT"),
        ("runtime.workers", "RUNTIME_WORKERS"),
        (
            "filing_extraction.source_batch_size",
            "FILING_EXTRACTION_SOURCE_BATCH_SIZE",
        ),
        ("sec.user_agent", "SEC_USER_AGENT"),
        ("group.with-hyphen", "GROUP_WITH_HYPHEN"),
    ],
)
def test_environment_names_are_generated_from_logical_paths(logical, expected):
    assert environment_name(logical) == expected


def test_phase_specs_collect_alongside_shared_specs():
    specs = collect_specs("filing_extraction")
    assert "filing_extraction.source_batch_size" in specs
    assert "runtime.threads" in specs
    assert "metadata.max_failure_attempts" not in specs

    metadata = collect_specs("metadata")
    assert "metadata.max_failure_attempts" in metadata


def test_unknown_phase_is_rejected():
    with pytest.raises(ValueError, match="unknown phase"):
        collect_specs("nope")


# --- typed parsing -------------------------------------------------------------


@pytest.mark.parametrize(
    ("value_type", "raw", "expected"),
    [
        (int, "5", 5),
        (int, "0", 0),
        (float, "0.5", 0.5),
        (bool, "true", True),
        (bool, "no", False),
        (bool, "ON", True),
        (str, "hello", "hello"),
    ],
)
def test_typed_parsing(value_type, raw, expected):
    spec = SettingSpec(value_type=value_type, default=None, env=True)
    parsed = settings_mod._parse_value(spec, "group.x", raw)
    assert parsed == expected


def test_path_type_parses_to_path():
    spec = SettingSpec(value_type=Path, default=None, env=True)
    assert settings_mod._parse_value(spec, "group.x", "/tmp/x") == Path("/tmp/x")


def test_invalid_typed_value_names_the_setting_path():
    spec = SettingSpec(value_type=int, default=None, env=True)
    with pytest.raises(ValueError, match="setting 'group.x' expects int"):
        settings_mod._parse_value(spec, "group.x", "not-an-int")


def test_invalid_boolean_names_the_setting_path():
    spec = SettingSpec(value_type=bool, default=None, env=True)
    with pytest.raises(ValueError, match="setting 'group.x' expects a boolean"):
        settings_mod._parse_value(spec, "group.x", "maybe")


# --- resolution precedence -------------------------------------------------------


def test_direct_environment_beats_dotenv_beats_factory(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("RUNTIME_THREADS=5\n", encoding="utf-8")
    monkeypatch.delenv("RUNTIME_THREADS", raising=False)
    monkeypatch.setenv("DOTENV_PATH", str(dotenv))
    monkeypatch.setattr("defs.runtime.resources.default_threads", lambda: 3)

    assert get_setting("runtime.threads") == 5

    monkeypatch.setenv("RUNTIME_THREADS", "9")
    assert get_setting("runtime.threads") == 9


def test_explicit_env_mapping_bypasses_process_and_dotenv(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("RUNTIME_THREADS=5\n", encoding="utf-8")
    monkeypatch.setenv("RUNTIME_THREADS", "9")
    monkeypatch.setenv("DOTENV_PATH", str(dotenv))

    resolved = resolve_settings(include=["runtime"], env={"RUNTIME_THREADS": "2"})
    assert resolved["runtime.threads"] == 2


def test_cli_override_beats_environment(tmp_path):
    resolved = resolve_settings(
        include=["runtime"],
        env={"RUNTIME_THREADS": "9"},
        cli_overrides={"runtime.threads": 4},
    )
    assert resolved["runtime.threads"] == 4


def test_persistable_setting_env_beats_config_beats_default():
    resolved = resolve_settings(
        phase="filing_extraction",
        config={"filing_extraction.source_batch_size": 42},
        env={"FILING_EXTRACTION_SOURCE_BATCH_SIZE": "7"},
    )
    assert resolved["filing_extraction.source_batch_size"] == 7

    resolved = resolve_settings(
        phase="filing_extraction",
        config={"filing_extraction.source_batch_size": 42},
    )
    assert resolved["filing_extraction.source_batch_size"] == 42

    resolved = _resolve_all(phase="filing_extraction")
    assert resolved["filing_extraction.source_batch_size"] == 1000


def test_settings_without_env_flag_ignore_environment(monkeypatch):
    fake_specs = {"group.no_env": SettingSpec(value_type=int, default=4, env=False)}
    monkeypatch.setattr(
        settings_mod, "collect_specs", lambda phase=None: dict(fake_specs)
    )
    monkeypatch.setenv("GROUP_NO_ENV", "99")
    assert get_setting("group.no_env") == 4


def test_unknown_setting_path_raises_value_error():
    with pytest.raises(ValueError, match="unknown setting"):
        get_setting("group.nope")


# --- false, zero, and empty values -------------------------------------------------


def test_explicit_zero_environment_value_is_rejected_for_threads():
    with pytest.raises(ValueError, match="runtime.threads"):
        _resolve_all(env={"RUNTIME_THREADS": "0"})


def test_explicit_false_environment_value_is_preserved(monkeypatch):
    fake_specs = {"group.flag": SettingSpec(value_type=bool, default=True, env=True)}
    monkeypatch.setattr(
        settings_mod, "collect_specs", lambda phase=None: dict(fake_specs)
    )
    resolved = settings_mod.resolve_settings(env={"GROUP_FLAG": "false"})
    assert resolved["group.flag"] is False


def test_empty_environment_value_is_treated_as_unset(monkeypatch):
    monkeypatch.setattr("defs.runtime.resources.default_threads", lambda: 6)
    resolved = _resolve_all(env={"RUNTIME_THREADS": ""})
    assert resolved["runtime.threads"] == 6


def test_fallbacks_supply_values_for_specs_without_defaults(monkeypatch):
    fake_specs = {"group.x": SettingSpec(default=MISSING)}
    monkeypatch.setattr(
        settings_mod, "collect_specs", lambda phase=None: dict(fake_specs)
    )
    resolved = settings_mod.resolve_settings(
        include=["group"], env={}, fallbacks={"group.x": "supplied"}
    )
    assert resolved["group.x"] == "supplied"


def test_missing_value_without_default_or_fallback_raises(monkeypatch):
    fake_specs = {"group.x": SettingSpec(default=MISSING)}
    monkeypatch.setattr(
        settings_mod, "collect_specs", lambda phase=None: dict(fake_specs)
    )
    with pytest.raises(ValueError, match="'group.x' has no value"):
        settings_mod.resolve_settings(env={})


# --- machine-derived factories ------------------------------------------------------


def test_machine_derived_factory_runs_and_env_overrides(monkeypatch):
    monkeypatch.setattr("defs.runtime.resources.default_threads", lambda: 3)
    assert get_setting("runtime.threads", env={}) == 3
    assert get_setting("runtime.threads", env={"RUNTIME_THREADS": "4"}) == 4


def test_dependent_factory_uses_resolved_fraction(monkeypatch):
    monkeypatch.setattr(
        "defs.runtime.resources._physical_memory_bytes", lambda: 10 * 1024**3
    )
    monkeypatch.setattr("defs.runtime.resources.psutil", None)
    resolved = resolve_settings(
        include=["runtime"], env={"RUNTIME_MEMORY_FRACTION": "0.5"}
    )
    assert resolved["runtime.memory_limit"] == "5120MiB"


def test_validate_hook_names_the_setting_path():
    with pytest.raises(ValueError, match="runtime.memory_fraction"):
        resolve_settings(include=["runtime"], env={"RUNTIME_MEMORY_FRACTION": "2"})


# --- secrets and reports --------------------------------------------------------------


def test_secret_setting_resolves_but_is_excluded_from_flattened_settings():
    resolved = _resolve_all(env={"SEC_USER_AGENT": "Agent/1.0 a@b.com"})
    assert resolved["sec.user_agent"] == "Agent/1.0 a@b.com"
    flattened = flatten_settings(resolved)
    assert "sec.user_agent" not in flattened
    assert "runtime.workers" in flattened


def test_render_dotenv_never_contains_secret_values():
    specs = collect_specs()
    resolved = _resolve_all(env={"SEC_USER_AGENT": "Agent/1.0 a@b.com"})
    text = render_dotenv(specs, resolved)
    assert "a@b.com" not in text
    assert "SEC_USER_AGENT is omitted on purpose" in text


# --- dotenv rendering -------------------------------------------------------------------


def test_environment_names_match_documented_legacy_names():
    assert environment_name("artifacts.root") == "ARTIFACTS_ROOT"
    assert environment_name("cache.root") == "CACHE_ROOT"
    assert environment_name("runtime.threads") == "RUNTIME_THREADS"
    assert environment_name("sec.user_agent") == "SEC_USER_AGENT"


def test_render_dotenv_groups_by_top_level_segment():
    text = render_dotenv(collect_specs(), _resolve_all())
    indices = {
        group: text.index(f"# {group}")
        for group in ("artifacts", "cache", "runtime", "sec")
    }
    ordered = sorted(indices, key=indices.__getitem__)
    assert ordered == ["artifacts", "cache", "runtime", "sec"]


# --- generated dotenv file ----------------------------------------------------------------


def test_generate_dotenv_refuses_overwrite_without_force(tmp_path):
    target = tmp_path / ".env"
    generate_dotenv(target)
    with pytest.raises(ValueError, match="--force"):
        generate_dotenv(target)
    generate_dotenv(target, force=True)


def test_generate_dotenv_output_is_ascii_safe(tmp_path):
    target = tmp_path / ".env"
    generate_dotenv(target)
    Path(target).read_bytes().decode("ascii")
