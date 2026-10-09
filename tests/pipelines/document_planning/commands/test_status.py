from __future__ import annotations

import argparse
from types import SimpleNamespace

from edgar_sec.pipelines.document_planning.commands import status as command


def test_status_reports_profile_and_plan_manifests(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        command,
        "resolve_document_planning_paths",
        lambda **_kw: SimpleNamespace(profiles_root="profiles", plans_root="plans"),
    )
    monkeypatch.setattr(command, "discover_profiles", lambda _root: ())
    monkeypatch.setattr(command, "discover_document_plans", lambda _paths: ())

    assert command.cmd_status(argparse.Namespace(artifacts="", json=True)) == 0
    assert capsys.readouterr().out.strip() == '{"plans": [], "profiles": []}'
