"""Tests for the table_classification operator surface."""

from __future__ import annotations

from edgar_sec.foundation.runtime.interactive import MenuAction, MenuSeparator
from edgar_sec.pipelines.table_classification import operator
from edgar_sec.pipelines.table_classification.paths import ClassificationPaths
from edgar_sec.pipelines.table_classification.planner import build_plan
from edgar_sec.pipelines.table_classification.translator import plan_request_for


def test_operator_menu_and_session_header() -> None:
    session = operator.OperatorSession(snapshot_id="snap-1", plan_id="plan-1")
    assert "snapshot=snap-1" in session.header()
    assert "plan=plan-1" in session.header()
    menu = operator.build_operator_menu(session)
    assert any(isinstance(item, MenuSeparator) for item in menu)
    assert sum(isinstance(item, MenuAction) for item in menu) == 5


def test_operator_translate_action_renders_triples(monkeypatch, capsys) -> None:  # noqa: ANN001
    rendered = []
    monkeypatch.setattr(
        operator,
        "render_output",
        lambda rows, title=None: rendered.append((rows, title)),
    )
    operator._action_translate(operator.OperatorSession())
    rows, _title = rendered[0]
    assert "EX-13" in rows[0].value


def test_operator_drill_reads_a_written_plan(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    request = plan_request_for(("0001-26-1",), source_snapshot_id="snap-1")
    result = build_plan(request, ClassificationPaths(artifacts_root=tmp_path))
    options = operator.SurfaceOptions(
        plans_root=tmp_path / "table_classification" / "plans"
    )
    monkeypatch.setattr(operator, "SurfaceOptions", lambda: options)
    monkeypatch.setattr(
        operator,
        "prompt_paginated_choice",
        lambda items, prompt_label=None, default=None: items[0],
    )
    rendered = []
    monkeypatch.setattr(
        operator,
        "render_output",
        lambda rows, title=None: rendered.append((rows, title)),
    )
    session = operator.OperatorSession()
    operator._action_inspect(session)
    assert session.plan_id == result.plan_id
    assert rendered[0][1] == "plan drill"
