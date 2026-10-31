from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.pipelines.document_inventory.commands import project as project_command


def test_project_is_offline_and_reports_pinned_inputs(tmp_path, monkeypatch, capsys):
    cohort_path = tmp_path / "cohort.parquet"
    pq.write_table(pa.table({"accession": pa.array(["a", "b"])}), cohort_path)
    paths = SimpleNamespace(cohort_accessions_path=lambda: cohort_path)
    projection = SimpleNamespace(
        run_id="run-1",
        catalog_plan_id="plan-1",
        base_snapshot_id="snapshot-1",
        work_order_rows=1,
        work_order_digest="d" * 64,
        paths=paths,
    )
    calls = []
    monkeypatch.setattr(
        project_command,
        "project_catalog_plan",
        lambda *args, **kwargs: calls.append((args, kwargs)) or projection,
    )
    monkeypatch.setattr(
        project_command,
        "read_run_manifest",
        lambda _paths: SimpleNamespace(chunk_size=128),
    )
    args = Namespace(
        artifacts_root=str(tmp_path),
        catalog_plan="plan-1",
        base_snapshot_id=None,
        branch="main",
        chunk_size=None,
        explicit_refresh=False,
        json=True,
    )

    assert project_command.cmd_project(args) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["run_id"] == "run-1"
    assert result["branch"] == "main"
    assert result["cohort_accession_rows"] == 2
    assert result["work_order_rows"] == 1
    assert result["chunk_size"] == 128
    assert calls[0][1]["branch_name"] == "main"
