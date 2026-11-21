from __future__ import annotations

import argparse
from types import SimpleNamespace

from edgar_sec.pipelines.document_planning.commands import inspect as command
from edgar_sec.pipelines.document_planning.discovery import DocumentPlanError


def test_inspect_refuses_invalid_bundle(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        command,
        "read_published_plan",
        lambda *_args: (_ for _ in ()).throw(DocumentPlanError("bad digest")),
    )
    args = argparse.Namespace(artifacts="", plan_id="dplan-x", json=False)

    assert command.cmd_inspect(args) == 2
    assert "bad digest" in capsys.readouterr().out


def test_inspect_text_renders_key_values_and_parts_grid(monkeypatch, capsys) -> None:
    manifest = {
        "plan_digest": "digest-plan",
        "profile_id": "prof-alpha",
        "profile_version": 3,
        "catalog_plan_id": "cat-9",
        "catalog_plan_digest": "digest-cat",
        "inventory_snapshot_id": "snap-7",
        "inventory_snapshot_digest": "digest-snap",
        "distinct_accession_coverage": {
            "catalog_scope": 100,
            "inventory_indexed": 80,
            "inventory_unindexed": 20,
            "matched": 80,
        },
        "target_row_count": 12345,
        "status_counts": {"matched": 90, "unmatched": 10},
        "origin_counts": {"catalog": 100},
        "reason_counts": {"ok": 90, "no_document": 10},
        "parts": [
            {"path": "parts/p0.parquet", "rows": 10000, "sha256": "sha-p0"},
            {"path": "parts/p1.parquet", "rows": 2345, "sha256": "sha-p1"},
        ],
    }
    monkeypatch.setattr(
        command,
        "resolve_document_planning_paths",
        lambda **_kw: SimpleNamespace(),
    )
    monkeypatch.setattr(
        command,
        "read_published_plan",
        lambda *_args: SimpleNamespace(plan_id="dplan-2026-001", manifest=manifest),
    )
    args = argparse.Namespace(artifacts="", plan_id="dplan-2026-001", json=False)

    assert command.cmd_inspect(args) == 0
    lines = [line.rstrip() for line in capsys.readouterr().out.splitlines()]
    assert lines == [
        "validated document plan dplan-2026-001",
        "  catalog plan        cat-9 (digest-cat)",
        "  inventory snapshot  snap-7 (digest-snap)",
        "  coverage            {'catalog_scope': 100, 'inventory_indexed': 80, "
        "'inventory_unindexed': 20, 'matched': 80}",
        "  target rows         12,345",
        "  statuses            {'matched': 90, 'unmatched': 10}",
        "  origins             {'catalog': 100}",
        "  reasons             {'ok': 90, 'no_document': 10}",
        "  Part              Rows   SHA256",
        "  ----------------  -----  ------",
        "  parts/p0.parquet  10000  sha-p0",
        "  parts/p1.parquet  2345   sha-p1",
    ]
