"""The pipeline's authority values and the registered defaults cannot drift apart."""

from __future__ import annotations

from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.foundation.runtime.settings.catalog import DEFAULT_TARGET_BYTES
from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_READ_BATCH_SIZE


def test_read_batch_size_is_registered_and_matches_the_shared_default() -> None:
    settings = resolve_settings()
    assert settings["runtime.read_batch_size"] == DEFAULT_READ_BATCH_SIZE
    assert DEFAULT_READ_BATCH_SIZE == 4096


def test_document_payload_target_bytes_is_registered_and_matches_vacuum() -> None:
    settings = resolve_settings()
    assert settings["documents.payload_target_bytes"] == DEFAULT_TARGET_BYTES
    assert DEFAULT_TARGET_BYTES == 96 * 1024 * 1024


def test_document_and_runtime_settings_are_env_overridable() -> None:
    """``env=True`` is the whole point of registering: an env override must win."""
    from edgar_sec.foundation.runtime.settings import collect_specs, environment_name

    specs = collect_specs()
    for logical in ("runtime.read_batch_size", "documents.payload_target_bytes"):
        spec = specs[logical]
        assert spec.env, f"{logical} is not env-overridable"
        name = environment_name(logical)
        assert name.startswith(("RUNTIME_", "DOCUMENTS_")), name


def test_document_settings_are_not_persisted_to_config() -> None:
    """Machine-derived values stay machine-local, per AGENTS.md's precedence rules."""
    from edgar_sec.foundation.runtime.settings import collect_specs

    specs = collect_specs()
    for logical in ("runtime.read_batch_size", "documents.payload_target_bytes"):
        assert not specs[logical].config, (
            f"{logical} is registered with config=True but no backing store exists"
        )
