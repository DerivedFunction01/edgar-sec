"""Smoke-test guards, offline: the live path is credential-gated and excluded from
the default gate, so only its pure guards are proven here.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar_sec.pipelines.metadata_sync import smoke_test as smoke
from edgar_sec.pipelines.metadata_sync.smoke_test import build_parser, main
from tests.pipelines.metadata_sync.cohort_support import publish_test_cohort
from tests.support import fixture_path


def test_cohort_and_artifacts_root_are_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--cohort", "uploaded"])


def test_chunk_size_defaults_to_none_so_the_registry_decides() -> None:
    args = build_parser().parse_args(
        [
            "--cohort",
            "uploaded",
            "--artifacts",
            "preview/metadata",
        ]
    )
    assert args.chunk_size is None
    assert args.workers is None
    assert args.sample_size == 3


def test_chunk_size_can_be_overridden() -> None:
    args = build_parser().parse_args(
        [
            "--cohort",
            "uploaded",
            "--artifacts",
            "preview/metadata",
            "--chunk-size",
            "2",
        ]
    )
    assert args.chunk_size == 2


def test_a_production_artifacts_root_is_refused(tmp_path: Path, capsys) -> None:
    """The guard that makes a manual smoke run safe to perform."""
    production = tmp_path / ".artifacts" / "metadata"
    exit_code = main(
        [
            "--cohort",
            "uploaded",
            "--artifacts",
            str(production),
        ]
    )
    assert exit_code == 2
    assert "preview directory" in capsys.readouterr().err


def _fake_run_chunk(statuses: list[str], captured: dict[str, object]):
    """A genuine Parquet checkpoint, because the report is read back from it."""

    def run(client, plan, run_paths, chunk_id, **kwargs):
        from edgar_sec.engine.submissions.builder import build_submission_table
        from edgar_sec.infra.storage.parquet import write_parquet_table

        captured["snapshot_id"] = kwargs["snapshot_id"]
        captured["plan_id"] = plan.plan_id
        rows = [
            _row(cik, plan.input_fingerprint, kwargs["snapshot_id"])
            for cik in plan.chunk_ciks(chunk_id)
        ]
        for index, status in enumerate(statuses):
            rows[index]["status"] = status
            rows[index]["error"] = "boom" if status == "failed" else None
        path = run_paths.chunk_file(chunk_id)
        write_parquet_table(build_submission_table(rows), path)
        return SimpleNamespace(
            chunk_id=chunk_id,
            row_count=len(rows),
            path=str(path),
            skipped_existing=False,
            statuses={"ok": sum(1 for row in rows if row["status"] == "ok")},
            historical_files=[],
        )

    return run


def _row(cik: str, fingerprint: str, snapshot_id: str) -> dict:
    return {
        "cik": cik,
        "name": f"COMPANY {cik}",
        "tickers": [],
        "exchanges": [],
        "sic": "",
        "sic_description": "",
        "ein": "",
        "state_of_incorporation": "",
        "fiscal_year_end": "",
        "former_names": [],
        "addresses": [],
        "phone": "",
        "entity_type": "",
        "category": "",
        "entity_filings": 0,
        "filings": [],
        "filings_recent": 0,
        "filings_historical": 0,
        "filings_downloaded": 0,
        "status": "ok",
        "error": None,
        "snapshot_id": snapshot_id,
        "input_name": "sample.csv",
        "input_fingerprint": fingerprint,
        "cik_padded": cik,
    }


def test_a_preview_root_is_accepted(tmp_path: Path, monkeypatch, capsys) -> None:
    """A preview root passes the guard and reaches the fetch path."""
    preview = tmp_path / "preview" / "metadata"
    captured: dict[str, object] = {}
    record, _paths, _roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), tmp_path
    )
    resolve_options = smoke.plan_options
    monkeypatch.setattr(
        smoke,
        "plan_options",
        lambda **kwargs: resolve_options(**kwargs, artifacts_root=tmp_path),
    )

    monkeypatch.setattr(smoke, "_build_client", lambda artifacts_root: object())
    monkeypatch.setattr(smoke, "run_chunk", _fake_run_chunk(["ok", "ok"], captured))

    assert (
        main(
            [
                "--cohort",
                record.cohort_id,
                "--artifacts",
                str(preview),
                "--sample-size",
                "2",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "smoke test passed (no snapshot published)" in out
    assert "sampled 2 CIK(s)" in out
    # The smoke test never publishes, and its rows carry the plan identity.
    assert captured["snapshot_id"] == captured["plan_id"]
    assert not (preview / "snapshots").exists()
    assert not (preview / "current").exists()


def test_a_failed_sample_exits_nonzero(tmp_path: Path, monkeypatch, capsys) -> None:
    preview = tmp_path / "preview" / "metadata"
    captured: dict[str, object] = {}
    record, _paths, _roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), tmp_path
    )
    resolve_options = smoke.plan_options
    monkeypatch.setattr(
        smoke,
        "plan_options",
        lambda **kwargs: resolve_options(**kwargs, artifacts_root=tmp_path),
    )

    monkeypatch.setattr(smoke, "_build_client", lambda artifacts_root: object())
    monkeypatch.setattr(smoke, "run_chunk", _fake_run_chunk(["failed"], captured))

    assert (
        main(
            [
                "--cohort",
                record.cohort_id,
                "--artifacts",
                str(preview),
                "--sample-size",
                "1",
            ]
        )
        == 1
    )
    captured_out = capsys.readouterr()
    assert "failed" in captured_out.out
    assert "1 sampled CIK(s) failed" in captured_out.err
