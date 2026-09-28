"""Unit tests for foundation runtime, memory, hashing, serialization, and resource management."""

from __future__ import annotations

import hashlib
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.runtime.env import (
    get_env,
    get_env_bool,
    get_env_float,
    get_env_int,
    load_dotenv,
)
from edgar_sec.foundation.runtime.memory import reclaim, sha256_text
from edgar_sec.foundation.runtime.partitions import (
    divide_ids_among_workers,
    parse_id_selection,
)
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.foundation.runtime.resources import (
    auto_worker_count,
    available_memory_bytes,
    default_cpu_cores,
    default_memory_limit,
    derive_resources,
    usable_memory_bytes,
)
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.foundation.serialization import canonical_hash, canonical_json


def test_hashing_and_serialization(tmp_path: Path) -> None:
    test_file = tmp_path / "hello.txt"
    test_file.write_text("hello world", encoding="utf-8")
    assert (
        file_sha256(test_file)
        == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    )
    assert sha256_bytes(b"hello world") == file_sha256(test_file)

    obj1 = {"b": 2, "a": 1}
    obj2 = {"a": 1, "b": 2}
    assert canonical_json(obj1) == '{"a":1,"b":2}'
    assert canonical_hash(obj1) == canonical_hash(obj2)


def test_memory_reclaim_and_stream_hash() -> None:
    reclaim()  # Must not crash on any platform
    short_text = "test string"
    expected_short = hashlib.sha256(short_text.encode("utf-8")).hexdigest()
    assert sha256_text(short_text) == expected_short

    # Multi-megabyte text to exercise streaming chunks
    long_text = "A" * (2 * 1024 * 1024 + 50)
    expected_long = hashlib.sha256(long_text.encode("utf-8")).hexdigest()
    assert sha256_text(long_text) == expected_long


def test_resources_and_cgroup_awareness() -> None:
    avail = available_memory_bytes()
    assert avail > 0

    usable = usable_memory_bytes(avail)
    assert 0 <= usable <= avail

    cores = default_cpu_cores()
    assert cores >= 1

    workers = auto_worker_count(avail, worker_memory_mib=512, cpu_cores=cores)
    assert 1 <= workers <= cores

    mem_lim = default_memory_limit()
    assert mem_lim.endswith("MiB")

    res = derive_resources()
    assert res.cpu_cores >= 1
    assert res.worker_threads >= 1
    assert res.memory_limit_mb >= 256
    assert res.temp_dir.is_dir()
    assert Path(res.temp_directory).is_dir()


def test_env_and_dotenv_parsing(tmp_path: Path) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text(
        """
        # Comment line
        SEC_USER_AGENT=Test Corp Admin@test.com
        CONCURRENCY=8
        RATE_LIMIT=3.5
        DEBUG_MODE=true
        EMPTY_VAR=
        QUOTED_VAL="quoted string"
        """,
        encoding="utf-8",
    )
    parsed = load_dotenv(env_file)
    assert parsed["SEC_USER_AGENT"] == "Test Corp Admin@test.com"
    assert parsed["QUOTED_VAL"] == "quoted string"

    assert get_env("SEC_USER_AGENT", dotenv_path=env_file) == "Test Corp Admin@test.com"
    assert get_env_int("CONCURRENCY", default=4, dotenv_path=env_file) == 8
    assert get_env_float("RATE_LIMIT", default=1.0, dotenv_path=env_file) == 3.5
    assert get_env_bool("DEBUG_MODE", default=False, dotenv_path=env_file) is True


def test_paths_and_settings(tmp_path: Path) -> None:
    from edgar_sec.foundation.runtime.settings import resolve_runtime_settings

    paths = resolve_paths(repo_root=tmp_path)
    assert paths.repo_root == tmp_path
    assert paths.artifacts_root == tmp_path / ".artifacts"
    paths.ensure_directories()
    assert paths.artifacts_root.is_dir()

    settings_dict = resolve_settings()
    assert float(settings_dict["sec.rate_limit_rps"]) > 0
    assert int(settings_dict["runtime.chunk_size"]) > 0

    runtime = resolve_runtime_settings()
    assert runtime.sec.rate_limit_rps > 0
    assert runtime.default_chunk_size > 0
    assert runtime.sec.header_user_agent


def test_partitions_selection_and_worker_division() -> None:
    assert parse_id_selection("1-3,5,8-10") == (1, 2, 3, 5, 8, 9, 10)
    assert parse_id_selection("  4  ") == (4,)
    assert parse_id_selection("") == ()

    divided = divide_ids_among_workers((1, 2, 3, 4, 5, 6, 7), worker_count=3)
    assert len(divided) == 3
    # Check all elements preserved
    all_elements = sorted([item for bucket in divided for item in bucket])
    assert all_elements == [1, 2, 3, 4, 5, 6, 7]
