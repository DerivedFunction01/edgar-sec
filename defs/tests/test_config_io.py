from __future__ import annotations

import json
from pathlib import Path

import pytest

from defs.runtime.config_io import read_json_config, write_json_config


def test_write_and_read_json_config_roundtrip(tmp_path):
    config_file = tmp_path / "config.json"
    payload = {"foo": "bar", "num": 42}
    written = write_json_config(config_file, payload, version=1)
    assert Path(written).exists()

    version, loaded = read_json_config(config_file, expected_version=1)
    assert version == 1
    assert loaded == payload


def test_read_json_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="config not found at"):
        read_json_config(tmp_path / "missing.json")


def test_read_json_config_invalid_json_raises(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("invalid json", encoding="utf-8")
    with pytest.raises(ValueError, match="config file is not valid JSON"):
        read_json_config(bad_file)


def test_read_json_config_non_object_raises(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="config file must be a JSON object"):
        read_json_config(bad_file)


def test_read_json_config_version_mismatch_raises(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps({"version": 2, "config": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported config version"):
        read_json_config(bad_file, expected_version=1)


def test_read_json_config_missing_payload_key_raises(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps({"version": 1, "other": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="config file must contain a 'config' object"):
        read_json_config(bad_file, expected_version=1, payload_key="config")


def test_atomic_write_cleans_temporary_files(tmp_path):
    config_file = tmp_path / "config.json"
    write_json_config(config_file, {"a": 1})
    temp_files = list(tmp_path.glob(".config-*.tmp"))
    assert temp_files == []
    assert config_file.exists()
