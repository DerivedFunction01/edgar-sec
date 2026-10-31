from __future__ import annotations

import argparse

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
