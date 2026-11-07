"""Tests pinning the disk tier: budget, orphan reaping, vanished payloads."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from edgar_sec.apps.client.disk_tier import DiskTier


def _tier(tmp_path: Path, budget: int = 100_000) -> DiskTier:
    return DiskTier(tmp_path / "tier", budget)


def test_put_get_roundtrip_and_stats(tmp_path: Path) -> None:
    """Verify a placed payload reads back and lands in the statistics."""
    tier = _tier(tmp_path)
    assert tier.put("sections", "a", b"payload-a", source_id="sha-a") is True
    assert tier.get("sections", "a") == b"payload-a"
    assert tier.get("sections", "missing") is None
    stats = tier.stats()
    assert stats["entries"] == 1
    assert stats["current_bytes"] == len(b"payload-a")
    assert stats["budget_bytes"] == 100_000
    assert stats["hits"] == 1
    assert stats["misses"] == 1


def test_budget_must_be_positive(tmp_path: Path) -> None:
    """Verify a zero disk budget is refused."""
    with pytest.raises(ValueError):
        DiskTier(tmp_path / "tier", 0)


def test_oversize_payload_is_refused(tmp_path: Path) -> None:
    """Verify a payload larger than the whole budget is never stored."""
    tier = _tier(tmp_path, budget=10)
    assert tier.put("sections", "a", b"x" * 11) is False
    assert tier.stats()["entries"] == 0


def test_budget_evicts_coldest_down_to_the_target(tmp_path: Path) -> None:
    """Verify inserts past budget evict coldest-by-last-access to ~90%."""
    tier = _tier(tmp_path, budget=1_000)
    for index in range(4):
        assert tier.put("sections", f"k{index}", bytes([index]) * 300) is True
        time.sleep(0.02)
    stats = tier.stats()
    assert stats["current_bytes"] == 900
    assert stats["entries"] == 3
    assert stats["evictions"] == 1
    assert tier.get("sections", "k0") is None
    assert tier.get("sections", "k3") == bytes([3]) * 300
    assert tier.get("sections", "k1") is not None
    time.sleep(0.02)
    assert tier.put("sections", "k4", b"z" * 300) is True
    assert tier.get("sections", "k2") is None
    assert tier.get("sections", "k1") is not None


def test_orphan_files_are_reaped_on_open(tmp_path: Path) -> None:
    """Verify files no index row references vanish when the tier reopens."""
    root = tmp_path / "tier"
    tier = DiskTier(root, 100_000)
    tier.put("sections", "a", b"payload-a")
    tier.close()
    stray_dir = root / "files" / "zz"
    stray_dir.mkdir(parents=True, exist_ok=True)
    stray = stray_dir / "deadbeef.bin"
    stray.write_bytes(b"orphan")
    leftover = stray_dir / "abc.bin.tmp.123"
    leftover.write_bytes(b"partial")
    reopened = DiskTier(root, 100_000)
    assert not stray.exists()
    assert not leftover.exists()
    assert reopened.get("sections", "a") == b"payload-a"


def test_missing_payload_file_is_a_miss_and_drops_the_row(tmp_path: Path) -> None:
    """Verify a vanished payload reads as a miss, never as an error."""
    tier = _tier(tmp_path)
    tier.put("sections", "a", b"payload-a")
    payload_files = list((tmp_path / "tier" / "files").rglob("*.bin"))
    assert len(payload_files) == 1
    payload_files[0].unlink()
    assert tier.get("sections", "a") is None
    assert tier.get("sections", "a") is None
    assert tier.stats()["entries"] == 0
    assert tier.stats()["misses"] == 2


def test_shared_payload_file_survives_one_keys_delete(tmp_path: Path) -> None:
    """Verify content-keyed sharing: one file, two rows, delete keeps both safe."""
    tier = _tier(tmp_path)
    tier.put("sections", "a", b"same-bytes")
    tier.put("notes", "a", b"same-bytes")
    files = list((tmp_path / "tier" / "files").rglob("*.bin"))
    assert len(files) == 1
    tier.delete("sections", "a")
    assert tier.get("notes", "a") == b"same-bytes"
    assert files[0].exists()


def test_two_instances_interleave_on_one_root(tmp_path: Path) -> None:
    """Verify two tiers over one root (WAL) serve each other's writes."""
    root = tmp_path / "tier"
    first = DiskTier(root, 100_000)
    second = DiskTier(root, 100_000)
    first.put("sections", "a", b"from-first")
    assert second.get("sections", "a") == b"from-first"
    second.put("sections", "b", b"from-second")
    assert first.get("sections", "b") == b"from-second"
    assert first.stats()["entries"] == 2


def test_clear_drops_rows_and_files(tmp_path: Path) -> None:
    """Verify clear empties the ledger and the payload directory."""
    tier = _tier(tmp_path)
    tier.put("sections", "a", b"payload-a")
    tier.put("sections", "b", b"payload-b")
    tier.clear()
    stats = tier.stats()
    assert stats["entries"] == 0
    assert stats["current_bytes"] == 0
    assert list((tmp_path / "tier" / "files").rglob("*.bin")) == []
    assert tier.get("sections", "a") is None
