from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from edgar_sec.pipelines.document_planning.commands import plan as command


def test_plan_command_reports_published_plan(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    paths = SimpleNamespace(artifacts_root=tmp_path)
    manifest = {
        "catalog_plan_id": "catalog-1",
        "catalog_plan_digest": "a" * 64,
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
        "target_row_count": 3,
        "distinct_accession_coverage": {"catalog_scope": 2, "matched": 1},
        "status_counts": {"matched": 2, "unresolved": 1},
    }
    monkeypatch.setattr(command, "resolve_document_planning_paths", lambda **_kw: paths)
    monkeypatch.setattr(
        command,
        "create_document_plan",
        lambda *_args: SimpleNamespace(
            plan_id="dplan-1", root=tmp_path, manifest=manifest, reused=False
        ),
    )
    args = argparse.Namespace(
        artifacts="",
        catalog_plan="catalog-1",
        profile_id="profile",
        inventory=None,
        json=True,
    )

    assert command.cmd_plan(args) == 0
    assert '"target_row_count": 3' in capsys.readouterr().out


def _stub_plan(monkeypatch, snapshot_id) -> None:
    manifest = {
        "catalog_plan_id": "cat-9",
        "catalog_plan_digest": "digest-cat",
        "inventory_snapshot_id": snapshot_id,
        "inventory_snapshot_digest": "digest-snap" if snapshot_id else None,
        "target_row_count": 12345,
        "distinct_accession_coverage": {
            "catalog_scope": 100,
            "inventory_indexed": 80,
            "inventory_unindexed": 20,
            "matched": 80,
        },
        "status_counts": {"matched": 90, "unmatched": 10},
    }
    monkeypatch.setattr(
        command,
        "resolve_document_planning_paths",
        lambda **_kw: SimpleNamespace(profiles_root="profiles", plans_root="plans"),
    )
    monkeypatch.setattr(
        command,
        "create_document_plan",
        lambda *_args: SimpleNamespace(
            plan_id="dplan-2026-001",
            root=Path("plans/dplan-2026-001"),
            manifest=manifest,
            reused=False,
        ),
    )


def test_plan_text_renders_key_values(monkeypatch, capsys) -> None:
    _stub_plan(monkeypatch, "snap-7")
    args = argparse.Namespace(
        artifacts="",
        catalog_plan="cat-9",
        profile_id="prof-alpha",
        inventory="snap-7",
        json=False,
    )

    assert command.cmd_plan(args) == 0
    lines = [line.rstrip() for line in capsys.readouterr().out.splitlines()]
    assert lines == [
        "published document plan dplan-2026-001",
        "  target rows         12,345",
        "  catalog plan        cat-9",
        "  inventory snapshot  snap-7",
        "  accession coverage  {'catalog_scope': 100, 'inventory_indexed': 80, "
        "'inventory_unindexed': 20, 'matched': 80}",
        "  status counts       {'matched': 90, 'unmatched': 10}",
        "  path                plans/dplan-2026-001",
    ]


def test_plan_text_omits_snapshot_row_when_absent(monkeypatch, capsys) -> None:
    _stub_plan(monkeypatch, None)
    args = argparse.Namespace(
        artifacts="",
        catalog_plan="cat-9",
        profile_id="prof-alpha",
        inventory=None,
        json=False,
    )

    assert command.cmd_plan(args) == 0
    lines = [line.rstrip() for line in capsys.readouterr().out.splitlines()]
    assert lines == [
        "published document plan dplan-2026-001",
        "  target rows         12,345",
        "  catalog plan        cat-9",
        "  accession coverage  {'catalog_scope': 100, 'inventory_indexed': 80, "
        "'inventory_unindexed': 20, 'matched': 80}",
        "  status counts       {'matched': 90, 'unmatched': 10}",
        "  path                plans/dplan-2026-001",
    ]
