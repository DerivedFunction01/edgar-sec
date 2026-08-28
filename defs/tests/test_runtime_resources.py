from __future__ import annotations

import pytest

from defs.runtime import resources
from defs.runtime.settings import resolve_settings


def test_resources_use_explicit_environment_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNTIME_WORKERS", "6")
    monkeypatch.setenv("RUNTIME_THREADS", "3")
    monkeypatch.setenv("RUNTIME_MEMORY_LIMIT", "2GB")
    monkeypatch.setenv("RUNTIME_TEMP_DIRECTORY", str(tmp_path / "container-tmp"))

    result = resources.derive_resources()

    assert result.workers == 6
    assert result.threads == 3
    assert result.memory_limit == "2GB"
    assert result.temp_directory == str((tmp_path / "container-tmp").resolve())


def test_resources_resolve_through_the_canonical_dotenv(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RUNTIME_THREADS=5\nRUNTIME_MEMORY_LIMIT=4GB\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("RUNTIME_THREADS", raising=False)
    monkeypatch.delenv("RUNTIME_MEMORY_LIMIT", raising=False)
    monkeypatch.setenv("DOTENV_PATH", str(env_file))
    monkeypatch.setattr(resources, "default_threads", lambda: 8)

    result = resources.derive_resources()

    assert result.threads == 5
    assert result.memory_limit == "4GB"


def test_explicit_env_mapping_bypasses_process_and_dotenv(tmp_path):
    result = resources.derive_resources(
        env={
            "RUNTIME_WORKERS": "4",
            "RUNTIME_THREADS": "2",
            "RUNTIME_MEMORY_LIMIT": "1GB",
            "RUNTIME_TEMP_DIRECTORY": str(tmp_path / "mapped-tmp"),
        }
    )

    assert result.workers == 4
    assert result.threads == 2
    assert result.memory_limit == "1GB"
    assert result.temp_directory == str((tmp_path / "mapped-tmp").resolve())


def test_resources_default_from_machine_probe(monkeypatch):
    monkeypatch.delenv("RUNTIME_WORKERS", raising=False)
    monkeypatch.delenv("RUNTIME_THREADS", raising=False)
    monkeypatch.delenv("RUNTIME_MEMORY_LIMIT", raising=False)
    monkeypatch.delenv("RUNTIME_MEMORY_FRACTION", raising=False)
    monkeypatch.delenv("RUNTIME_TEMP_DIRECTORY", raising=False)
    monkeypatch.setattr(resources, "default_threads", lambda: 8)
    monkeypatch.setattr(resources, "_physical_memory_bytes", lambda: 10 * 1024**3)
    monkeypatch.setattr(resources, "psutil", None)

    result = resources.derive_resources()

    assert result.threads == 8
    assert result.memory_limit == "6144MiB"
    assert result.temp_directory.endswith("edgar-sec-spill")


def test_memory_fraction_setting_scales_machine_probe(monkeypatch):
    monkeypatch.setattr(resources, "_physical_memory_bytes", lambda: 10 * 1024**3)
    monkeypatch.setattr(resources, "psutil", None)

    result = resources.derive_resources(env={"RUNTIME_MEMORY_FRACTION": "0.5"})

    assert result.memory_limit == "5120MiB"


def test_invalid_memory_fraction_is_rejected_with_setting_path():
    with pytest.raises(ValueError, match="runtime.memory_fraction"):
        resolve_settings(include=["runtime"], env={"RUNTIME_MEMORY_FRACTION": "1.5"})


def test_default_threads_clamps_to_at_least_one(monkeypatch):
    monkeypatch.setattr(resources, "psutil", None)
    monkeypatch.setattr(resources.os, "cpu_count", lambda: 0)
    assert resources.default_threads() == 1


def test_default_memory_limit_rejects_out_of_range_fraction():
    with pytest.raises(ValueError, match="between 0 and 1"):
        resources.default_memory_limit(1.5)
