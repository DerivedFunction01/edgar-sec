"""Phase 02 config resolution through the shared settings registry."""

from __future__ import annotations

import importlib
import json

import pytest

phase_config = importlib.import_module("phases.02_filing_extraction.core.config")
phase_settings = importlib.import_module("phases.settings")


def test_load_without_config_uses_spec_default(tmp_path, monkeypatch):
    monkeypatch.delenv("FILING_EXTRACTION_SOURCE_BATCH_SIZE", raising=False)
    config = phase_config.load(tmp_path / "missing.json")
    assert config.source_batch_size == phase_config.DEFAULT_SOURCE_BATCH_SIZE


def test_persisted_config_value_is_used(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"version": 1, "config": {"source_batch_size": 250}}),
        encoding="utf-8",
    )
    assert phase_config.load(config_path).source_batch_size == 250


def test_environment_overrides_persisted_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"version": 1, "config": {"source_batch_size": 250}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FILING_EXTRACTION_SOURCE_BATCH_SIZE", "75")
    assert phase_config.load(config_path).source_batch_size == 75


def test_empty_environment_value_falls_back_to_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"version": 1, "config": {"source_batch_size": 250}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FILING_EXTRACTION_SOURCE_BATCH_SIZE", "")
    assert phase_config.load(config_path).source_batch_size == 250


def test_explicit_env_mapping_bypasses_process_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FILING_EXTRACTION_SOURCE_BATCH_SIZE", "75")
    config = phase_config.load(
        tmp_path / "missing.json", env={"FILING_EXTRACTION_SOURCE_BATCH_SIZE": "9"}
    )
    assert config.source_batch_size == 9


def test_invalid_environment_value_names_the_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("FILING_EXTRACTION_SOURCE_BATCH_SIZE", "many")
    with pytest.raises(ValueError, match="filing_extraction.source_batch_size"):
        phase_config.load(tmp_path / "missing.json")


def test_invalid_persisted_batch_size_is_rejected(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"version": 1, "config": {"source_batch_size": 0}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source_batch_size must be >= 1"):
        phase_config.load(config_path)


def test_phase_barrel_maps_filing_extraction_to_its_settings_module():
    assert (
        phase_settings.PHASE_SETTING_MODULES["filing_extraction"]
        == "phases.02_filing_extraction.settings"
    )
    module = importlib.import_module(
        phase_settings.phase_settings_module("filing_extraction")
    )
    assert "filing_extraction.source_batch_size" in _flatten(module.SETTING_SPECS)


def _flatten(group, prefix=""):
    paths = []
    for name, value in group.items():
        path = f"{prefix}.{name}" if prefix else name
        if isinstance(value, dict):
            paths.extend(_flatten(value, path))
        else:
            paths.append(path)
    return paths
