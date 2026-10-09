"""Operator wizard: state, discovery, and command delegation; a binding that
drifts from the command surface fails only in an interactive session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest, PartDescriptor
from edgar_sec.pipelines.metadata_sync import augment_flow
from edgar_sec.pipelines.metadata_sync import operator as operator_module
from edgar_sec.pipelines.metadata_sync.cli import (
    cmd_merge,
    cmd_plan,
    cmd_run,
    cmd_status,
)
from edgar_sec.pipelines.metadata_sync.discovery import current_snapshot_id
from edgar_sec.pipelines.metadata_sync.merger import publish_current_snapshot
from edgar_sec.pipelines.metadata_sync.operator import (
    INTERRUPTED_MESSAGE,
    MENU_TITLE,
    WizardState,
    _ask_int,
    _ask_plan_options,
    _ask_run_options,
    _ensure_plan,
    build_operator_menu,
    confirm_network,
    main,
    render_plan_header,
    render_session_header,
    resolve_plan,
)
from edgar_sec.pipelines.metadata_sync.options import (
    derive_plan_id,
    plan_options,
    run_options,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from tests.pipelines.metadata_sync.cohort_support import publish_test_cohort
from tests.support import fixture_path

COMMANDS = {
    "plan": cmd_plan,
    "status": cmd_status,
    "run": cmd_run,
    "merge": cmd_merge,
}


@pytest.fixture()
def state(tmp_path: Path) -> WizardState:
    return WizardState(artifacts_root=str(tmp_path))


def _write_plan(tmp_path: Path, *, chunk_size: int = 2) -> str:
    record, _paths, roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), tmp_path
    )
    plan = build_plan(
        roster,
        chunk_size=chunk_size,
        input_name=f"cohort:{record.cohort_id}",
        input_fingerprint=record.dataset_sha256,
    )
    write_plan(plan, resolve_run_paths(plan.plan_id, tmp_path))
    return plan.plan_id


def _cohort_id(artifacts: Path) -> str:
    return publish_test_cohort(fixture_path("cik_sec_mini.csv"), artifacts)[0].cohort_id


# ------------------------------------------------------------------------ menu


def test_menu_covers_the_whole_lifecycle() -> None:
    menu = build_operator_menu()
    labels = {action.key: action.label for action in menu}
    assert "d" in labels and "distribution" in labels["d"].lower()
    assert "p" in labels and (
        "dag" in labels["p"].lower() or "snapshot" in labels["p"].lower()
    )
    assert any("Plan" in label for label in labels.values())
    assert any("Augment" in label for label in labels.values())
    assert not any(
        term in label.casefold()
        for label in labels.values()
        for term in ("source", "cohort", "family-index")
    )
    assert MENU_TITLE.startswith("Metadata Sync")


def test_every_menu_action_binds_to_a_shared_command() -> None:
    """A menu entry that points nowhere is how a command becomes dead surface."""
    for action in build_operator_menu():
        assert action.callback.__name__ == "<lambda>"
        assert callable(action.callback)


def test_menu_closes_over_the_supplied_state() -> None:
    """Two menus must not share one session, or a test leaks into the next."""
    first, second = WizardState(), WizardState()
    first.plan_id = "aaaa"
    assert build_operator_menu(first) is not build_operator_menu(second)


# ------------------------------------------------------------------ prompting


def test_blank_numeric_answers_defer_to_the_settings_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    assert _ask_int("anything") is None
    assert _ask_int("anything", 7) is None


def test_an_unparsable_answer_falls_back_rather_than_crashing(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "abc")
    assert _ask_int("anything", 7) is None
    assert "not a whole number" in capsys.readouterr().out


def test_ask_plan_options_returns_none_on_cancel(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(operator_module, "_ask_published_cohort", lambda _state: None)
    assert _ask_plan_options(state, with_limit=True) is None


def test_ask_plan_options_uses_registered_defaults(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "17")
    monkeypatch.setattr(
        operator_module,
        "_ask_published_cohort",
        lambda _state: plan_options(cohort="c-test"),
    )
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    options = _ask_plan_options(state)
    assert options is not None
    assert options.cohort == "c-test"
    assert options.chunk_size == 17


def test_ask_plan_options_records_a_limit(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        operator_module,
        "_ask_published_cohort",
        lambda _state: plan_options(cohort="c-test"),
    )
    answers = iter(["1000", "3"])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    options = _ask_plan_options(state, with_limit=True)
    assert options is not None
    assert options.limit == 3


# -------------------------------------------------- the restored core behavior


def test_a_blank_plan_id_falls_back_to_the_working_plan(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It must resolve, not return ``None`` and drop the operator at the menu."""
    state.plan_id = "0123456789abcdef"
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    options = _ask_run_options(state)
    assert options is not None
    assert options.plan_id == "0123456789abcdef"


def test_a_blank_plan_id_discovers_a_plan_when_none_is_established(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_id = _write_plan(tmp_path, chunk_size=2)
    monkeypatch.setattr("builtins.input", lambda _: "")
    options = _ask_run_options(state)
    assert options is not None
    assert options.plan_id == plan_id
    assert state.plan_id == plan_id


def test_working_plan_is_preserved_without_reprompt(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.plan_id = "plan-active"
    monkeypatch.setattr("builtins.input", lambda _: "")
    options = _ask_run_options(state)
    assert options is not None and options.plan_id == "plan-active"
    assert state.plan_id == "plan-active"


def test_an_in_progress_run_is_adopted_with_default(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_id = _write_plan(tmp_path, chunk_size=2)
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert _ensure_plan(state) is True
    assert state.plan_id == plan_id


def test_several_plans_are_offered_as_a_numbered_pick(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(tmp_path, chunk_size=4)
    second = _write_plan(tmp_path, chunk_size=2)
    monkeypatch.setattr("builtins.input", lambda _: "1")
    assert resolve_plan(state) is True
    assert state.plan_id == second


def test_a_cancelled_pick_leaves_no_plan_established(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(tmp_path, chunk_size=4)
    _write_plan(tmp_path, chunk_size=2)
    monkeypatch.setattr("builtins.input", lambda _: "q")
    assert resolve_plan(state) is False
    assert state.plan_id == ""


def test_no_plan_is_reported_not_silently_ignored(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "1")
    assert resolve_plan(state) is False
    assert "No plan on disk" in capsys.readouterr().out


def test_a_published_snapshot_offers_augment_when_no_plan_exists(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    metadata = state.metadata()
    catalog = DAGCatalog(metadata.snapshots_root)
    catalog.write_pointer("main", "abc123")

    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "0")
    assert resolve_plan(state) is False
    assert "abc123" in capsys.readouterr().out


def test_the_working_plan_survives_across_menu_visits(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """State is the point: visiting the menu must not cost the operator a re-ask."""
    plan_id = _write_plan(tmp_path, chunk_size=2)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert _ensure_plan(state) is True
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_status", seen.append)
    operator_module.status(state)
    operator_module.status(state)
    assert len(seen) == 2
    assert state.plan_id == plan_id


# ------------------------------------------------------------------------ header


def test_header_is_absent_until_a_plan_is_resolved(state: WizardState) -> None:
    assert render_plan_header(state) is None


def test_header_describes_the_working_plan(state: WizardState, tmp_path: Path) -> None:
    state.plan_id = _write_plan(tmp_path, chunk_size=2)
    header = render_plan_header(state)
    assert header is not None
    assert state.plan_id in header
    assert "4 CIKs" in header
    assert "0/2 chunks" in header


def test_header_says_so_when_the_plan_cannot_be_read(state: WizardState) -> None:
    state.plan_id = "does-not-exist"
    header = render_plan_header(state)
    assert header is not None and "does-not-exist" in header


def test_session_header_names_the_plan_and_the_published_snapshot(
    state: WizardState, tmp_path: Path
) -> None:
    """The header is what makes the session's target visible without running status."""
    state.plan_id = _write_plan(tmp_path, chunk_size=2)
    catalog = DAGCatalog(state.metadata().snapshots_root)
    catalog.write_pointer("main", "abc123")

    header = render_session_header(state)
    assert state.plan_id in header
    assert "abc123" in header


def test_session_header_admits_an_unresolved_session(state: WizardState) -> None:
    header = render_session_header(state)
    assert "No plan selected" in header
    assert "no snapshot published" in header


# ------------------------------------------------------------ network consent


@pytest.mark.parametrize(
    "answer,expected", [("y", True), ("YES", True), ("n", False), ("", False)]
)
def test_network_confirmation_defaults_to_no(
    monkeypatch: pytest.MonkeyPatch, answer: str, expected: bool
) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: answer)
    assert confirm_network() is expected


def test_a_declined_run_fetches_nothing(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    state.plan_id = "0123456789abcdef"
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: False)
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_run", seen.append)
    operator_module.run(state)
    assert seen == []
    assert "nothing was fetched" in capsys.readouterr().out


# ------------------------------------------------------------------- delegation


def test_action_plan_records_the_plan_it_created(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        operator_module,
        "_ask_plan_options",
        lambda *a, **k: plan_options(
            cohort=_cohort_id(tmp_path), artifacts_root=tmp_path
        ),
    )
    monkeypatch.setattr(operator_module, "cmd_plan", lambda options: None)
    operator_module.plan(state)
    assert state.plan_id == derive_plan_id(
        plan_options(cohort=_cohort_id(tmp_path), artifacts_root=tmp_path)
    )


def test_action_status_delegates_to_cmd_status(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.plan_id = "p"
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_status", seen.append)
    operator_module.status(state)
    assert len(seen) == 1


def test_action_run_forwards_a_chunk_selection(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.plan_id = "p"
    monkeypatch.setattr(
        operator_module,
        "prompt_text",
        lambda label, default: "0,2" if "Chunk" in label else default,
    )
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: True)
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_run", seen.append)
    operator_module.run(state)
    assert seen[0].chunk_ids == (0, 2)


def test_action_run_leaves_the_selection_empty_when_blank(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.plan_id = "p"
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: True)
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_run", seen.append)
    operator_module.run(state)
    assert seen[0].chunk_ids == ()


def test_action_merge_delegates_to_cmd_merge(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.plan_id = "p"
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_merge", seen.append)
    operator_module.merge(state)
    assert len(seen) == 1


def test_cancelled_answers_short_circuit_every_action(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(operator_module, "_ask_plan_options", lambda *a, **k: None)
    monkeypatch.setattr(operator_module, "_ask_run_options", lambda *a, **k: None)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    monkeypatch.setattr(operator_module, "_ensure_plan", lambda _s: False)
    # Augmentation asks its cohort question in augment_flow now; still an action.
    monkeypatch.setattr(augment_flow, "ask_augment_cohort", lambda *a, **k: None)
    called: list[object] = []
    for command in COMMANDS.values():
        monkeypatch.setattr(
            operator_module,
            command.__name__,
            lambda *a, _n=command.__name__, **k: called.append(_n),
        )
    monkeypatch.setattr(
        augment_flow,
        "cmd_augment",
        lambda *a, **k: called.append("cmd_augment"),
    )
    operator_module.plan(state)
    operator_module.status(state)
    operator_module.run(state)
    operator_module.merge(state)
    operator_module.augment(state)
    operator_module.open_metadata_distrib_console(state)
    assert called == []


# ----------------------------------------------------------------- the pointer


def _record_snapshot(metadata, snapshot_id: str, row_count: int = 1) -> None:
    DAGCatalog(metadata.snapshots_root).record_node(
        DAGNodeManifest(
            snapshot_id=snapshot_id,
            kind="checkpoint",
            parents=(),
            checkpoint_anchor_id=snapshot_id,
            lineage_depth=0,
            created_at="2026-10-09T00:00:00Z",
            relations={
                "submissions": (
                    PartDescriptor("parts/data.parquet", "sha", row_count, 1),
                )
            },
            logical_fingerprint=f"fp-{snapshot_id}",
            metadata={"kind": "full", "row_count": row_count},
        )
    )


def test_selecting_a_snapshot_moves_the_current_pointer(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A merge can only advance the pointer; this is what moves it back."""
    metadata = state.metadata()
    for snapshot_id in ("newer", "older"):
        _record_snapshot(metadata, snapshot_id, 7)
    publish_current_snapshot(metadata, "newer")

    monkeypatch.setattr(
        operator_module,
        "list_snapshots",
        lambda _paths: [
            {"snapshot_id": "newer", "row_count": 7},
            {"snapshot_id": "older", "row_count": 3},
        ],
    )
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "2")
    operator_module.select_snapshot(state)

    assert current_snapshot_id(metadata) == "older"
    assert "current snapshot is now older" in capsys.readouterr().out


def test_keeping_the_current_pointer_is_not_a_switch(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Blank keeps it, because moving the pointer back is a deliberate act."""
    metadata = state.metadata()
    _record_snapshot(metadata, "only")
    publish_current_snapshot(metadata, "only")

    monkeypatch.setattr(
        operator_module, "list_snapshots", lambda _paths: [{"snapshot_id": "only"}]
    )
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    operator_module.select_snapshot(state)

    assert current_snapshot_id(metadata) == "only"
    assert "unchanged" in capsys.readouterr().out


def test_selecting_an_unpublished_snapshot_leaves_the_pointer_alone(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Pointing at a snapshot absent from the DAG catalog is refused."""
    metadata = state.metadata()
    _record_snapshot(metadata, "known")
    publish_current_snapshot(metadata, "known")

    monkeypatch.setattr(
        operator_module,
        "list_snapshots",
        lambda _paths: [{"snapshot_id": "known"}, {"snapshot_id": "missing"}],
    )
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "2")
    operator_module.select_snapshot(state)

    assert current_snapshot_id(metadata) == "known"
    assert "could not switch snapshot" in capsys.readouterr().out


def test_selecting_a_snapshot_with_nothing_published_says_so(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(operator_module, "list_snapshots", lambda _paths: [])
    operator_module.select_snapshot(state)
    assert "no published snapshots" in capsys.readouterr().out


# ------------------------------------------------------------------- entrypoint


def test_main_dispatches_a_command_argument_to_the_cli(tmp_path: Path, capsys) -> None:
    cohort_id = _cohort_id(tmp_path)
    exit_code = main(
        [
            "plan",
            "--cohort",
            cohort_id,
            "--artifacts",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    assert "plan_id" in capsys.readouterr().out


def test_main_delegates_a_command_to_the_cli(monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(
        operator_module, "cli_main", lambda argv: seen.append(argv) or 0
    )
    assert main(["status", "--plan-id", "p"]) == 0
    assert seen == [["status", "--plan-id", "p"]]


def test_main_states_that_completed_work_survives_an_interrupt(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    entered: list[str] = []

    def fake_menu(
        title, actions, exit_key="0", *, interrupted_message=None, before_menu=None
    ):
        entered.append(interrupted_message or "")
        if before_menu is not None:
            # The session header must reach the menu.
            rendered.append(before_menu() or "")
        # Drive only status; the rest prompt for a plan this test has not set up.
        for action in actions:
            if "status" in action.label.lower():
                try:
                    action.callback()
                except KeyboardInterrupt:
                    print(f"\n{interrupted_message or 'Action cancelled by user.'}")
        return 0

    rendered: list[str] = []
    monkeypatch.setattr(
        "edgar_sec.foundation.runtime.interactive.run_interactive_menu", fake_menu
    )
    monkeypatch.setattr(
        operator_module, "_ask_run_options", lambda *a, **k: run_options(plan_id="p")
    )
    monkeypatch.setattr(
        operator_module,
        "cmd_status",
        lambda options: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    assert main([]) == 0
    assert entered == [INTERRUPTED_MESSAGE]
    assert "No plan selected" in rendered[0]
    assert "preserved" in capsys.readouterr().out


def test_a_dispatched_command_never_resolves_session_state(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """With arguments there is no session, so nothing may be discovered or printed."""
    seen: list[list[str]] = []
    monkeypatch.setattr(
        operator_module, "cli_main", lambda argv: seen.append(argv) or 0
    )
    assert main(["status", "--plan-id", "p"]) == 0
    assert seen == [["status", "--plan-id", "p"]]
    assert "No plan selected" not in capsys.readouterr().out
