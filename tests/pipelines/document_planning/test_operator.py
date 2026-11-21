from __future__ import annotations

from types import SimpleNamespace

from edgar_sec.foundation.runtime.interactive import MenuAction, MenuSeparator
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
    monkeypatch.setattr(
        operator, "_profile_choice", lambda *_args, **_kw: ("profile-1", False)
    )
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


def test_action_plan_renders_preflight_and_published_blocks(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        operator, "resolve_document_planning_paths", lambda: SimpleNamespace()
    )
    monkeypatch.setattr(
        operator, "_catalog_choice", lambda _paths, _default=None: "cat-9"
    )
    monkeypatch.setattr(
        operator, "_profile_choice", lambda *_args, **_kw: ("prof-alpha", False)
    )
    monkeypatch.setattr(
        operator, "_snapshot_choice", lambda _paths, _default=None: "current"
    )
    monkeypatch.setattr(
        operator,
        "resolve_inventory_snapshot_id",
        lambda _snapshot, _paths: "snap-7-pinned",
    )
    monkeypatch.setattr(
        operator,
        "coverage_preflight",
        lambda _catalog, snapshot, _paths: SimpleNamespace(
            snapshot_id=snapshot,
            indexed_accessions=8000,
            unindexed_accessions=2000,
            scoped_accessions=10000,
        ),
    )
    monkeypatch.setattr(operator, "prompt_choice", lambda *_args, **_kwargs: "2")
    monkeypatch.setattr(operator, "prompt_text", lambda *_args, **_kwargs: "y")
    monkeypatch.setattr(
        operator,
        "create_document_plan",
        lambda *_args: SimpleNamespace(
            plan_id="dplan-2026-001",
            manifest={
                "catalog_plan_digest": "digest-cat",
                "inventory_snapshot_digest": "digest-snap",
                "distinct_accession_coverage": {
                    "catalog_scope": 100,
                    "inventory_indexed": 80,
                    "inventory_unindexed": 20,
                    "matched": 80,
                },
                "status_counts": {"matched": 90, "unmatched": 10},
            },
        ),
    )

    session = operator.OperatorSession()
    operator._action_plan(session)

    lines = [line.rstrip() for line in capsys.readouterr().out.splitlines()]
    assert lines == [
        "  resolved inventory snapshot  snap-7-pinned",
        "  read-only coverage           8,000 indexed / 2,000 unindexed of "
        "10,000 catalog accessions",
        "  project the selected accessions with 'inventory project' before planning",
        "published document plan dplan-2026-001",
        "  source pins  digest-cat / digest-snap",
        "  coverage     {'catalog_scope': 100, 'inventory_indexed': 80, "
        "'inventory_unindexed': 20, 'matched': 80}",
        "  statuses     {'matched': 90, 'unmatched': 10}",
    ]
    assert session.plan_id == "dplan-2026-001"


def test_menu_groups_actions_under_separators() -> None:
    menu = operator.build_operator_menu(operator.OperatorSession())

    assert [type(item) for item in menu] == [
        MenuSeparator,
        MenuAction,
        MenuSeparator,
        MenuAction,
        MenuAction,
    ]
    separators = [item for item in menu if isinstance(item, MenuSeparator)]
    actions = [item for item in menu if isinstance(item, MenuAction)]
    assert [item.title for item in separators] == ["Planning", "Published Plans"]
    assert [(item.key, item.label) for item in actions] == [
        ("1", "Plan document targets"),
        ("2", "Inspect a published plan"),
        ("3", "List plans and profiles"),
    ]
