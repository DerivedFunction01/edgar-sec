from __future__ import annotations

from types import SimpleNamespace

from edgar_sec.pipelines.document_planning import operator


def test_operator_requires_default_no_confirmation_after_coverage(
    monkeypatch, capsys
) -> None:
    events = []
    monkeypatch.setattr(
        operator, "resolve_document_planning_paths", lambda: SimpleNamespace()
    )
    monkeypatch.setattr(
        operator, "_catalog_choice", lambda _paths, _default=None: "catalog-1"
    )
    monkeypatch.setattr(operator, "_profile_choice", lambda *_args, **_kw: "profile-1")
    monkeypatch.setattr(
        operator, "_snapshot_choice", lambda _paths, _default=None: "current"
    )

    def resolve(snapshot, _paths):
        events.append(("resolve", snapshot))
        return "snapshot-pinned"

    def preflight(catalog, snapshot, _paths):
        events.append(("preflight", catalog, snapshot))
        return SimpleNamespace(
            snapshot_id=snapshot,
            indexed_accessions=3,
            unindexed_accessions=1,
            scoped_accessions=4,
        )

    monkeypatch.setattr(operator, "resolve_inventory_snapshot_id", resolve)
    monkeypatch.setattr(operator, "coverage_preflight", preflight)
    monkeypatch.setattr(
        operator,
        "prompt_choice",
        lambda *_args, **_kwargs: "2",
    )
    monkeypatch.setattr(
        operator,
        "prompt_text",
        lambda *_args, **_kwargs: "n",
    )
    monkeypatch.setattr(
        operator,
        "create_document_plan",
        lambda *_args: events.append(("published",)),
    )

    session = operator.OperatorSession()
    operator._action_plan(session)

    assert events == [
        ("resolve", "current"),
        ("preflight", "catalog-1", "snapshot-pinned"),
    ]
    assert "snapshot-pinned" in capsys.readouterr().out
    assert ("published",) not in events
    assert session.evidence_mode == "2"
    assert session.snapshot_id == "snapshot-pinned"


def test_session_defaults_are_shown_and_reused(monkeypatch) -> None:
    session = operator.OperatorSession(
        evidence_mode="2",
        catalog_plan_id="catalog-1",
        profile_id="profile-1",
        snapshot_id="snapshot-1",
        plan_id="dplan-1",
    )
    monkeypatch.setattr(
        operator, "resolve_document_planning_paths", lambda: SimpleNamespace()
    )
    defaults = []

    def choose(_label, _items, *, default=None):
        defaults.append(default)
        return "0"

    monkeypatch.setattr(operator, "prompt_choice", choose)

    operator._action_plan(session)

    assert defaults == ["2"]
    assert "catalog=catalog-1" in session.header()
    assert "snapshot=snapshot-1" in session.header()
