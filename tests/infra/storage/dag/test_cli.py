"""Tests for unified DAG CLI runner."""

from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.cli import (
    cmd_checkout,
    cmd_compact,
    cmd_doctor,
    cmd_gc,
    cmd_log,
    cmd_status,
    main,
)
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    write_manifest,
)
from edgar_sec.infra.storage.dag.publication import checkout_tip


def _setup_dag(tmp_path: Path) -> str:
    c0_dir = tmp_path / "c0"
    c0_dir.mkdir(parents=True)
    c0_file = c0_dir / "p1.parquet"
    c0_file.write_bytes(b"dummy-parquet-data")
    c0_manifest = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={
            "sub": (
                PartDescriptor(
                    "p1.parquet",
                    file_sha256(c0_file),
                    10,
                    c0_file.stat().st_size,
                ),
            )
        },
        logical_fingerprint="fp0",
    )
    c0_man_path = c0_dir / "manifest.json"
    write_manifest(c0_man_path, c0_manifest)

    d1_dir = tmp_path / "d1"
    d1_dir.mkdir(parents=True)
    d1_file = d1_dir / "p2.parquet"
    d1_file.write_bytes(b"dummy-parquet-delta")
    d1_manifest = DAGNodeManifest(
        snapshot_id="d1",
        kind="delta",
        parents=(ParentRef("c0", file_sha256(c0_man_path)),),
        checkpoint_anchor_id="c0",
        lineage_depth=1,
        created_at="2026-10-07T00:01:00Z",
        relations={
            "sub": (
                PartDescriptor(
                    "p2.parquet",
                    file_sha256(d1_file),
                    5,
                    d1_file.stat().st_size,
                ),
            )
        },
        logical_fingerprint="fp1",
    )
    write_manifest(d1_dir / "manifest.json", d1_manifest)
    checkout_tip(tmp_path, "d1")
    return "d1"


def test_cli_status(tmp_path: Path, capsys) -> None:
    assert cmd_status(tmp_path) == 1
    _setup_dag(tmp_path)
    assert cmd_status(tmp_path, as_json=True) == 0
    captured = capsys.readouterr()
    assert "d1" in captured.out


def test_cli_log(tmp_path: Path, capsys) -> None:
    _setup_dag(tmp_path)
    assert cmd_log(tmp_path, as_json=False) == 0
    captured = capsys.readouterr()
    assert "d1" in captured.out
    assert "c0" in captured.out


def test_cli_checkout(tmp_path: Path) -> None:
    _setup_dag(tmp_path)
    assert cmd_checkout(tmp_path, "c0") == 0


def test_cli_doctor_and_gc(tmp_path: Path) -> None:
    _setup_dag(tmp_path)
    assert cmd_doctor(tmp_path, as_json=True) == 0
    assert cmd_gc(tmp_path, dry_run=True, as_json=True) == 0


def test_cli_main_entrypoint(tmp_path: Path) -> None:
    _setup_dag(tmp_path)
    exit_code = main(["--root", str(tmp_path), "status"])
    assert exit_code == 0
