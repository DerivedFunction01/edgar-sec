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
