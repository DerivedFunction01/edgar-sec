"""Unit tests for foundation.runtime.resources."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.resources import (
    auto_worker_count,
    available_memory_bytes,
    default_cpu_cores,
    default_memory_limit,
    default_threads,
    derive_resources,
    usable_memory_bytes,
)


def test_memory_probes_are_positive() -> None:
    avail = available_memory_bytes()
    assert avail > 0

    usable = usable_memory_bytes(avail)
    assert 0 <= usable <= avail

    assert default_memory_limit().endswith("MiB")


def test_cpu_and_thread_counts_are_at_least_one() -> None:
    assert default_cpu_cores() >= 1
    assert default_threads() >= 1


def test_auto_worker_count_is_bounded_by_cores_and_memory() -> None:
    avail = available_memory_bytes()
    cores = default_cpu_cores()
    workers = auto_worker_count(avail, worker_memory_mib=512, cpu_cores=cores)
    assert 1 <= workers <= cores


def test_auto_worker_count_never_zero_under_tight_memory() -> None:
    assert auto_worker_count(1, worker_memory_mib=512) == 1


def test_usable_memory_bytes_rejects_bad_arguments() -> None:
    for kwargs in (
        {"safety_fraction": 0.0},
        {"safety_fraction": 1.5},
        {"reserve_bytes": -1},
    ):
        try:
            usable_memory_bytes(1000, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {kwargs}")


def test_derive_resources_produces_usable_profile() -> None:
    res = derive_resources()
    assert res.cpu_cores >= 1
    assert res.worker_threads >= 1
    assert res.workers >= 1
    assert res.memory_limit_mb >= 256
    assert res.temp_dir.is_dir()
    assert Path(res.temp_directory).is_dir()


def test_derive_resources_honors_thread_override() -> None:
    res = derive_resources(requested_threads=1)
    assert res.threads == 1
    assert res.workers == 1
