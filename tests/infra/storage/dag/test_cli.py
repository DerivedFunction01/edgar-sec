"""Tests for unified DAG CLI runner."""

from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.cli import (
    cmd_branch,
    cmd_checkout,
    cmd_compact,
    cmd_doctor,
    cmd_gc,
    cmd_log,
    cmd_publish,
    cmd_status,
    cmd_tag,
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


def test_cli_checkout_lineage_guard(tmp_path: Path) -> None:
    """Checkout to an unrelated snapshot is blocked without --force."""
    _setup_dag(tmp_path)

    # Create an unrelated snapshot not in d1's lineage
    unrelated_dir = tmp_path / "unrelated"
    unrelated_dir.mkdir(parents=True)
    unrelated_manifest = DAGNodeManifest(
        snapshot_id="unrelated",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="unrelated",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={},
        logical_fingerprint="fp_unrelated",
    )
    write_manifest(unrelated_dir / "manifest.json", unrelated_manifest)

    # Without --force, checkout to unrelated snapshot should fail
    assert cmd_checkout(tmp_path, "unrelated") == 1

    # With --force, checkout should succeed
    assert cmd_checkout(tmp_path, "unrelated", force=True) == 0


def test_cli_doctor_and_gc(tmp_path: Path) -> None:
    _setup_dag(tmp_path)
    assert cmd_doctor(tmp_path, as_json=True) == 0
    assert cmd_gc(tmp_path, dry_run=True, as_json=True) == 0


def test_cli_main_entrypoint(tmp_path: Path) -> None:
    _setup_dag(tmp_path)
    exit_code = main(["--root", str(tmp_path), "status"])
    assert exit_code == 0


def test_cli_publish_genesis(tmp_path: Path) -> None:
    """Verify dag publish supports genesis publication with --allow-null."""
    staged = tmp_path / "stage_genesis"
    staged.mkdir(parents=True)
    manifest = DAGNodeManifest(
        snapshot_id="g0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="g0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={},
        logical_fingerprint="fp_g",
    )
    write_manifest(staged / "manifest.json", manifest)
    assert cmd_publish(tmp_path, staged, allow_null=True) == 0
    assert cmd_status(tmp_path) == 0


def test_cli_branch_and_tag(tmp_path: Path) -> None:
    """Verify CLI branch and tag management subcommands."""
    _setup_dag(tmp_path)
    assert cmd_branch(tmp_path, action="create", name="exp") == 0
    assert cmd_branch(tmp_path, action="list") == 0
    assert (
        cmd_tag(tmp_path, action="create", name="v1", target="d1", message="test tag")
        == 0
    )
    assert cmd_tag(tmp_path, action="list") == 0
    assert cmd_checkout(tmp_path, "v1") == 0
    assert cmd_branch(tmp_path, action="delete", name="exp") == 0
    assert cmd_tag(tmp_path, action="delete", name="v1") == 0


def test_cli_log_graph(tmp_path: Path, capsys) -> None:
    """Verify CLI log --graph output with swimlanes."""
    _setup_dag(tmp_path)
    assert cmd_log(tmp_path, graph=True) == 0
    out = capsys.readouterr().out
    assert "d1" in out
    assert "c0" in out
