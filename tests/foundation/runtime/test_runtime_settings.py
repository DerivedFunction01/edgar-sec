"""Runtime settings specs: plan-defining bounds validate themselves, and no spec
declares `config=True` while no settings mapping is persisted. `partition_count`
is deliberately absent: nothing reads it.
"""

from __future__ import annotations

import pytest

from edgar_sec.foundation.runtime.settings import (
    RuntimeSettings,
    environment_name,
    resolve_runtime_settings,
    resolve_settings,
)
from edgar_sec.foundation.runtime.settings import runtime as runtime_specs
from edgar_sec.foundation.runtime.settings.runtime import (
    DEFAULT_CHUNK_SIZE,
    get_runtime_specs,
)
from edgar_sec.foundation.runtime.settings.validators import (
    validate_fraction,
    validate_non_negative_int,
    validate_positive_int,
)

PLAN_DEFINING = ("runtime.chunk_size",)


def _specs() -> dict:
    return {
        name: spec
        for group in get_runtime_specs().values()
        for name, spec in group.items()
    }


def test_the_module_constants_are_the_spec_defaults() -> None:
    specs = _specs()
    assert specs["chunk_size"].default == DEFAULT_CHUNK_SIZE
    assert DEFAULT_CHUNK_SIZE == 1000


def test_the_retired_partition_count_setting_is_gone() -> None:
    """A spec that resolves and addresses by env var implies an operator can change
    the behaviour; with no consumer it was accepted and silently discarded.
    """
    assert "partition_count" not in _specs()
    assert not hasattr(RuntimeSettings, "default_partition_count")
    assert "runtime.partition_count" not in resolve_settings()
    assert not hasattr(runtime_specs, "DEFAULT_PARTITION_COUNT")


def test_plan_defining_specs_are_env_and_cli_addressable() -> None:
    for path in PLAN_DEFINING:
        spec = _specs()[path.split(".")[1]]
        assert spec.env is True, path
        assert spec.cli is True, path
        assert environment_name(path) == path.replace(".", "_").upper()


def test_plan_defining_specs_declare_no_persistence() -> None:
    """``config=True`` advertises a store; no settings mapping is persisted."""
    for path in PLAN_DEFINING:
        assert _specs()[path.split(".")[1]].config is False, path


def test_plan_defining_specs_reject_non_positive_values() -> None:
    for path in PLAN_DEFINING:
        validate = _specs()[path.split(".")[1]].validate
        assert validate is validate_positive_int, path
        with pytest.raises(ValueError, match="must be >= 1"):
            validate(0)
        with pytest.raises(ValueError, match="must be >= 1"):
            validate(-1)


def test_runtime_settings_surface_the_resolved_chunking() -> None:
    settings: RuntimeSettings = resolve_runtime_settings()
    assert settings.default_chunk_size == DEFAULT_CHUNK_SIZE


def test_runtime_settings_accept_cli_overrides() -> None:
    settings = resolve_runtime_settings(cli_overrides={"runtime.chunk_size": 3})
    assert settings.default_chunk_size == 3


def test_resolution_rejects_an_invalid_override() -> None:
    with pytest.raises(ValueError, match="must be >= 1"):
        resolve_runtime_settings(cli_overrides={"runtime.chunk_size": 0})


def test_env_overrides_beat_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "9")
    resolved = resolve_settings(env={"RUNTIME_CHUNK_SIZE": "9"})
    assert resolved["runtime.chunk_size"] == 9


def test_machine_derived_specs_are_marked_local() -> None:
    """Machine facts must never be treated as reproducible run configuration."""
    specs = _specs()
    for name in (
        "threads",
        "memory_limit",
        "temp_directory",
        "worker_memory_mib",
        "worker_memory_safety",
    ):
        assert specs[name].machine_local is True, name
    for name in ("chunk_size",):
        assert specs[name].machine_local is False, name


def test_validators_enforce_their_documented_bounds() -> None:
    validate_positive_int(1)
    validate_non_negative_int(0)
    validate_fraction(1.0)
    validate_fraction(0.5)
    with pytest.raises(ValueError, match="must be >= 0"):
        validate_non_negative_int(-1)
    with pytest.raises(ValueError, match="must be between 0 and 1"):
        validate_fraction(0.0)
    with pytest.raises(ValueError, match="must be between 0 and 1"):
        validate_fraction(1.5)


def test_cache_settings_are_exposed_on_the_resolved_model() -> None:
    """A setting that exists and is read by no one is the same defect as a chunk size
    that exists and is ignored.
    """
    from pathlib import Path

    settings = resolve_runtime_settings()
    resolved = resolve_settings()

    assert settings.cache_root == Path(str(resolved["cache.root"]))
    assert settings.ttl_s == int(resolved["cache.ttl_s"])
    assert settings.ttl_s == 90 * 24 * 60 * 60


def test_cache_settings_honor_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACHE_ROOT", "/tmp/alternate-cache")
    monkeypatch.setenv("CACHE_TTL_S", "60")
    resolved = resolve_settings()
    assert str(resolved["cache.root"]) == "/tmp/alternate-cache"
    assert resolved["cache.ttl_s"] == 60
