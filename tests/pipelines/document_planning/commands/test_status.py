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


def test_status_text_renders_profiles_and_plans_as_grids(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        command,
        "resolve_document_planning_paths",
        lambda **_kw: SimpleNamespace(profiles_root="profiles", plans_root="plans"),
    )
    monkeypatch.setattr(
        command,
        "discover_profiles",
        lambda _root: (
            SimpleNamespace(
                profile_id="prof-alpha",
                valid=True,
                profile=SimpleNamespace(version=3, digest="digest-alpha"),
                error=None,
            ),
            SimpleNamespace(
                profile_id="prof-broken",
                valid=False,
                profile=None,
                error="bad profile file",
            ),
        ),
    )
    monkeypatch.setattr(
        command,
        "discover_document_plans",
        lambda _paths: (
            SimpleNamespace(
                plan_id="dplan-2026-001",
                plan=SimpleNamespace(
                    manifest={"profile_id": "prof-alpha", "target_row_count": 1234}
                ),
                error=None,
            ),
            SimpleNamespace(
                plan_id="dplan-broken", plan=None, error="manifest unreadable"
            ),
        ),
    )

    assert command.cmd_status(argparse.Namespace(artifacts="", json=False)) == 0
    lines = [line.rstrip() for line in capsys.readouterr().out.splitlines()]
    assert lines == [
        "document-planning profiles",
        "  Profile      Version  Status",
        "  -----------  -------  -------------------------",
        "  prof-alpha   v3       valid",
        "  prof-broken  v?       invalid: bad profile file",
        "published target plans",
        "  Plan            Rows  Status",
        "  --------------  ----  ----------------------------",
        "  dplan-2026-001  1234  manifest-valid",
        "  dplan-broken    None  invalid: manifest unreadable",
    ]
