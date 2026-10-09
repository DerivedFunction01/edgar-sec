"""Tests for bundle discovery and status inspection."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.distribution.discovery import (
    discover_bundles,
    resolve_bundle_choice,
)
from edgar_sec.infra.distribution.guards import write_bundle_manifest
from edgar_sec.infra.distribution.partition import build_assignment
from edgar_sec.infra.distribution.receipt import (
    RECEIPT_FILE,
    build_worker_receipt,
    write_receipt,
)


def test_discover_bundles_empty(tmp_path: Path) -> None:
    """Verifies empty directory returns no bundles."""
    assert discover_bundles(tmp_path) == []


def test_discover_bundles_states_and_filtering(tmp_path: Path) -> None:
    """Verifies discovered bundles classify pending and completed states."""
    b1 = tmp_path / "metadata" / "p1" / "worker_1"
    b2 = tmp_path / "metadata" / "p1" / "worker_2"
    asgn1 = build_assignment("metadata", "p1", "worker_1", (0,))
    asgn2 = build_assignment("metadata", "p1", "worker_2", (1,))
    write_bundle_manifest(b1, asgn1)
    write_bundle_manifest(b2, asgn2)

    chunk = b1 / "data.bin"
    chunk.write_bytes(b"chunk1")
    receipt = build_worker_receipt("metadata", "p1", "worker_1", (0,), 10, [chunk], b1)
    write_receipt(receipt, b1 / RECEIPT_FILE)

    discovered = discover_bundles(tmp_path, pipeline="metadata")
    assert len(discovered) == 2
    completed = [b for b in discovered if b.state == "completed"]
    pending = [b for b in discovered if b.state == "pending"]
    assert len(completed) == 1 and completed[0].worker_id == "worker_1"
    assert len(pending) == 1 and pending[0].worker_id == "worker_2"


def test_resolve_bundle_choice() -> None:
    """Verifies bundle choice helper resolves selection."""
    from edgar_sec.infra.distribution.discovery import DiscoveredBundle

    b1 = DiscoveredBundle(Path("b1"), "meta", "p1", "w1", 1, (0,), "pending")
    b2 = DiscoveredBundle(Path("b2"), "meta", "p1", "w2", 1, (1,), "completed")
    chosen = resolve_bundle_choice([b1, b2], select=lambda _: "2")
    assert chosen is not None and chosen.worker_id == "w2"
