"""Offline CLI guards and synthetic S4 progress-scale execution."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.pipelines.document_inventory.progress_scale_check import main


def test_large_simulation_requires_explicit_opt_in(tmp_path: Path) -> None:
    scratch = tmp_path / "scale-check"
    with pytest.raises(SystemExit):
        main(["--scratch", str(scratch)])
    assert not scratch.exists()


def test_artifact_root_and_nonempty_scratch_are_refused(tmp_path: Path, capsys) -> None:
    artifacts_scratch = (
        resolve_runtime_settings().artifacts_root.resolve() / "progress-scale-check"
    )
    assert main(["--run-simulation", "--scratch", str(artifacts_scratch)]) == 2
    assert not artifacts_scratch.exists()

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    sentinel = occupied / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    assert main(["--run-simulation", "--scratch", str(occupied)]) == 2
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert "empty directory" in capsys.readouterr().err


def test_rows_above_the_scale_bound_are_refused_before_writing(
    tmp_path: Path, capsys
) -> None:
    scratch = tmp_path / "too-large"
    assert (
        main(
            [
                "--run-simulation",
                "--scratch",
                str(scratch),
                "--rows",
                "236001",
            ]
        )
        == 2
    )
    assert not scratch.exists()
    assert "--rows must be between" in capsys.readouterr().err


def test_synthetic_execution_is_offline_recovers_and_never_publishes(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    def deny_network(*_args, **_kwargs):
        raise AssertionError("the offline progress check attempted network access")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    scratch = tmp_path / "scratch"
    assert (
        main(
            [
                "--run-simulation",
                "--scratch",
                str(scratch),
                "--rows",
                "5",
                "--chunk-size",
                "3",
                "--entries-per-accession",
                "2",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert result["transactions"] == 5
    assert result["outcome_rows"] == 5
    assert result["entry_rows"] == 10
    assert result["recovered_partial_rows"] == 1
    assert result["recovery_validated"] is True
    assert result["committed_chunks_validated"] == 2
    assert result["broker_calls"] == 0
    assert result["network_access"] == "none"
    assert result["snapshot_published"] is False
    assert result["duckdb_bytes"] > 0
    assert result["parquet_bytes"] > 0
    assert not (scratch / "document_inventory" / "snapshots" / "current.json").exists()
