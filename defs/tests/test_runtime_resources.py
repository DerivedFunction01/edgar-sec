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


def test_resources_default_from_machine_probe(monkeypatch, tmp_path):
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("DOTENV_PATH", str(empty_env))
    monkeypatch.delenv("RUNTIME_WORKERS", raising=False)
    monkeypatch.delenv("RUNTIME_THREADS", raising=False)
    monkeypatch.delenv("RUNTIME_MEMORY_LIMIT", raising=False)
    monkeypatch.delenv("RUNTIME_MEMORY_FRACTION", raising=False)
    monkeypatch.delenv("RUNTIME_TEMP_DIRECTORY", raising=False)
    monkeypatch.setattr(resources, "default_threads", lambda: 8)
    monkeypatch.setattr(resources, "_physical_memory_bytes", lambda: 10 * 1024**3)
    monkeypatch.setattr(resources, "psutil", None)

    result = resources.derive_resources(env={})

    assert result.threads == 8
    assert result.memory_limit == "6144MiB"
    assert result.temp_directory.endswith("edgar-sec-spill")


def test_memory_fraction_setting_scales_machine_probe(monkeypatch, tmp_path):
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("DOTENV_PATH", str(empty_env))
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


# --------------------------------------------------------------------------- #
# cgroup-aware available-memory probe


def test_available_memory_prefers_cgroup_v2_over_v1(monkeypatch):
    monkeypatch.setattr(resources, "read_cgroup_v2_available_bytes", lambda: 4000)
    monkeypatch.setattr(resources, "read_cgroup_v1_available_bytes", lambda: 2000)
    monkeypatch.setattr(resources, "read_proc_mem_available_bytes", lambda: 1000)
    monkeypatch.setattr(resources, "psutil", None)
    assert resources.available_memory_bytes() == 4000


def test_available_memory_falls_back_to_v1_when_v2_unset(monkeypatch):
    monkeypatch.setattr(resources, "read_cgroup_v2_available_bytes", lambda: None)
    monkeypatch.setattr(resources, "read_cgroup_v1_available_bytes", lambda: 2000)
    monkeypatch.setattr(resources, "read_proc_mem_available_bytes", lambda: 1000)
    monkeypatch.setattr(resources, "psutil", None)
    assert resources.available_memory_bytes() == 2000


def test_available_memory_falls_back_to_proc_mem_available(monkeypatch):
    monkeypatch.setattr(resources, "read_cgroup_v2_available_bytes", lambda: None)
    monkeypatch.setattr(resources, "read_cgroup_v1_available_bytes", lambda: None)
    monkeypatch.setattr(resources, "read_proc_mem_available_bytes", lambda: 1000)
    monkeypatch.setattr(resources, "psutil", None)
    assert resources.available_memory_bytes() == 1000


def test_available_memory_falls_back_to_sysconf_when_unconstrained(monkeypatch):
    monkeypatch.setattr(resources, "read_cgroup_v2_available_bytes", lambda: None)
    monkeypatch.setattr(resources, "read_cgroup_v1_available_bytes", lambda: None)
    monkeypatch.setattr(resources, "read_proc_mem_available_bytes", lambda: None)
    monkeypatch.setattr(resources, "psutil", None)
    monkeypatch.setattr(
        resources.os,
        "sysconf",
        lambda key: 100 if key == "SC_PHYS_PAGES" else 4096,
    )
    assert resources.available_memory_bytes() == 409600


def test_read_cgroup_v2_parses_limit_minus_current(tmp_path, monkeypatch):
    limit = tmp_path / "memory.max"
    current = tmp_path / "memory.current"
    limit.write_text("1048576\n")
    current.write_text("524288\n")
    monkeypatch.setattr(resources, "_CGROUP_V2_MEMORY_MAX", limit)
    monkeypatch.setattr(resources, "_CGROUP_V2_MEMORY_CURRENT", current)
    assert resources.read_cgroup_v2_available_bytes() == 524288


def test_read_cgroup_v2_returns_none_when_unlimited(tmp_path, monkeypatch):
    limit = tmp_path / "memory.max"
    current = tmp_path / "memory.current"
    limit.write_text("max\n")
    current.write_text("524288\n")
    monkeypatch.setattr(resources, "_CGROUP_V2_MEMORY_MAX", limit)
    monkeypatch.setattr(resources, "_CGROUP_V2_MEMORY_CURRENT", current)
    assert resources.read_cgroup_v2_available_bytes() is None


def test_read_cgroup_v2_handles_missing_or_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "_CGROUP_V2_MEMORY_MAX", tmp_path / "does-not-exist")
    monkeypatch.setattr(
        resources, "_CGROUP_V2_MEMORY_CURRENT", tmp_path / "does-not-exist"
    )
    assert resources.read_cgroup_v2_available_bytes() is None

    malformed = tmp_path / "memory.max"
    malformed.write_text("not-a-number\n")
    current = tmp_path / "memory.current"
    current.write_text("524288\n")
    monkeypatch.setattr(resources, "_CGROUP_V2_MEMORY_MAX", malformed)
    monkeypatch.setattr(resources, "_CGROUP_V2_MEMORY_CURRENT", current)
    assert resources.read_cgroup_v2_available_bytes() is None


def test_read_cgroup_v1_parses_limit_minus_usage(tmp_path, monkeypatch):
    limit = tmp_path / "memory.limit_in_bytes"
    usage = tmp_path / "memory.usage_in_bytes"
    limit.write_text("2097152\n")
    usage.write_text("1048576\n")
    monkeypatch.setattr(resources, "_CGROUP_V1_MEMORY_LIMIT", limit)
    monkeypatch.setattr(resources, "_CGROUP_V1_MEMORY_USAGE", usage)
    assert resources.read_cgroup_v1_available_bytes() == 1048576


# --------------------------------------------------------------------------- #
# safety-budget math and automatic worker count


def test_usable_memory_applies_safety_fraction_and_reserve():
    available = 1000 * resources._MEBIBYTE
    assert (
        resources.usable_memory_bytes(available, safety_fraction=0.5, reserve_bytes=0)
        == 500 * resources._MEBIBYTE
    )
    assert (
        resources.usable_memory_bytes(
            available, safety_fraction=1.0, reserve_bytes=10 * resources._MEBIBYTE
        )
        == 990 * resources._MEBIBYTE
    )


def test_usable_memory_clamps_to_zero():
    assert (
        resources.usable_memory_bytes(100, safety_fraction=0.5, reserve_bytes=1000) == 0
    )


def test_usable_memory_rejects_invalid_fraction():
    with pytest.raises(ValueError, match="safety_fraction"):
        resources.usable_memory_bytes(1000, safety_fraction=1.5)


def test_auto_worker_count_floors_and_clamps_to_one():
    # 10 MiB * 0.9 usable, per-worker 512 MiB -> 0 -> clamped to one worker.
    available = 10 * resources._MEBIBYTE
    assert (
        resources.auto_worker_count(
            available, worker_memory_mib=512, safety_fraction=0.9
        )
        == 1
    )


def test_auto_worker_count_divides_by_per_worker_estimate():
    available = 10 * resources._MEBIBYTE
    assert (
        resources.auto_worker_count(available, worker_memory_mib=2, safety_fraction=1.0)
        == 5
    )


def test_auto_worker_count_rejects_bad_estimate():
    with pytest.raises(ValueError, match="worker_memory_mib"):
        resources.auto_worker_count(1000, worker_memory_mib=0)


# --------------------------------------------------------------------------- #
# settings-driven worker sizing


def test_workers_setting_derives_from_available_memory(monkeypatch):
    monkeypatch.setattr(
        resources, "available_memory_bytes", lambda: 10 * resources._MEBIBYTE
    )
    result = resources.derive_resources(
        env={
            "RUNTIME_WORKER_MEMORY_MIB": "2",
            "RUNTIME_WORKER_MEMORY_SAFETY": "0.9",
        }
    )
    # 10 MiB * 0.9 = 9 MiB usable; per-worker 2 MiB -> floor(4.5) = 4.
    assert result.workers == 4
    assert result.available_memory_bytes == 10 * resources._MEBIBYTE
    assert result.worker_memory_mib == 2
    assert result.worker_memory_safety == 0.9


def test_workers_setting_explicit_env_override(monkeypatch):
    monkeypatch.setattr(
        resources, "available_memory_bytes", lambda: 10 * resources._MEBIBYTE
    )
    result = resources.derive_resources(env={"RUNTIME_WORKERS": "6"})
    assert result.workers == 6


def test_workers_setting_clamps_to_one_on_tiny_memory(monkeypatch):
    monkeypatch.setattr(resources, "available_memory_bytes", lambda: 1024)
    result = resources.derive_resources(env={})
    assert result.workers == 1


def test_invalid_worker_setting_rejected():
    with pytest.raises(ValueError, match="runtime.workers"):
        resolve_settings(include=["runtime"], env={"RUNTIME_WORKERS": "0"})


def test_invalid_worker_memory_mib_rejected():
    with pytest.raises(ValueError, match="runtime.worker_memory_mib"):
        resolve_settings(include=["runtime"], env={"RUNTIME_WORKER_MEMORY_MIB": "0"})


def test_invalid_worker_memory_safety_rejected():
    with pytest.raises(ValueError, match="runtime.worker_memory_safety"):
        resolve_settings(include=["runtime"], env={"RUNTIME_WORKER_MEMORY_SAFETY": "2"})
