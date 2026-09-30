"""Operator wizard tests: state, discovery, and command delegation.

Two failure classes are guarded here. The first is a binding that drifts from
the command surface -- an action pointing at a command that no longer reads an
argument the wizard sets -- which would fail only inside an interactive session
nobody runs in CI. The second is the regression this pass restored: a wizard that
asks for a plan id it was never shown, and silently does nothing when the answer
is blank. Every action must either work, ask, or say why it cannot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync import operator as operator_module
from edgar_sec.pipelines.metadata_sync.cli import (
    cmd_augment,
    cmd_compare,
    cmd_export,
    cmd_merge,
    cmd_plan,
    cmd_refresh,
    cmd_run,
    cmd_status,
    cmd_worker,
)
from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.operator import (
    DEFAULT_INPUT,
    INTERRUPTED_MESSAGE,
    MENU_TITLE,
    WizardState,
    _ask_int,
    _ask_plan_options,
    _ask_run_options,
    _ensure_plan,
    build_operator_menu,
    commands,
    confirm_network,
    main,
    render_plan_header,
    resolve_plan,
)
from edgar_sec.pipelines.metadata_sync.options import (
    derive_plan_id,
    plan_options,
    run_options,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from edgar_sec.pipelines.metadata_sync.roster import roster_from_manifest
from tests.support import fixture_path

COMMANDS = {
    "plan": cmd_plan,
    "status": cmd_status,
    "run": cmd_run,
    "merge": cmd_merge,
    "augment": cmd_augment,
    "export": cmd_export,
    "worker": cmd_worker,
    "refresh": cmd_refresh,
    "compare": cmd_compare,
}


@pytest.fixture()
def state(tmp_path: Path) -> WizardState:
    return WizardState(artifacts_root=str(tmp_path))


def _write_plan(tmp_path: Path, *, chunk_size: int = 2) -> str:
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    plan = build_plan(roster_from_manifest(manifest), chunk_size=chunk_size)
    write_plan(plan, resolve_run_paths(plan.plan_id, tmp_path))
    return plan.plan_id


# ------------------------------------------------------------------------ menu


def test_menu_covers_the_whole_lifecycle() -> None:
    menu = build_operator_menu()
    assert [action.key for action in menu] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "p",
    ]


def test_every_menu_action_binds_to_a_shared_command() -> None:
    """A menu entry that points nowhere is how a command becomes dead surface."""
    for action in build_operator_menu():
        assert action.callback.__name__ == "<lambda>"
        assert callable(action.callback)


def test_menu_labels_describe_the_phase() -> None:
    labels = [action.label for action in build_operator_menu()]
    assert any("Plan" in label for label in labels)
    assert any("Merge" in label for label in labels)
    assert any("Augment" in label for label in labels)
    assert MENU_TITLE.startswith("Metadata Sync")


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    assert _ask_plan_options(with_limit=True) is None


def test_ask_plan_options_uses_registered_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "17")
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    options = _ask_plan_options()
    assert options is not None
    assert options.input_path is not None
    assert options.input_path.name == Path(DEFAULT_INPUT).name
    assert options.chunk_size == 17


def test_ask_plan_options_records_a_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([str(fixture_path("cik_sec_mini.csv")), "1000", "3"])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    options = _ask_plan_options(with_limit=True)
    assert options is not None
    assert options.limit == 3


# -------------------------------------------------- the restored core behavior


def test_a_blank_plan_id_falls_back_to_the_working_plan(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression: a blank answer used to do nothing at all.

    It must now resolve to the session's plan rather than returning ``None`` and
    dropping the operator back at the menu with no explanation.
    """
    state.plan_id = "0123456789abcdef"
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    options = _ask_run_options(state)
    assert options is not None
    assert options.plan_id == "0123456789abcdef"


def test_a_blank_plan_id_discovers_a_plan_when_none_is_established(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_id = _write_plan(tmp_path, chunk_size=2)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    options = _ask_run_options(state)
    assert options is not None
    assert options.plan_id == plan_id
    assert state.plan_id == plan_id


def test_an_explicit_plan_id_replaces_the_working_one(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.plan_id = "old"
    answers = iter(["new", ""])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    options = _ask_run_options(state)
    assert options is not None and options.plan_id == "new"
    assert state.plan_id == "new"


def test_an_in_progress_run_is_adopted_without_asking(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v1 auto-resumed the newest in-progress run; a single plan is adopted here."""
    plan_id = _write_plan(tmp_path, chunk_size=2)

    def must_not_prompt(_label: str, _default: str = "") -> str:
        raise AssertionError("a lone plan should not be put to the operator")

    monkeypatch.setattr(operator_module, "prompt_text", must_not_prompt)
    assert _ensure_plan(state) is True
    assert state.plan_id == plan_id


def test_several_plans_are_offered_as_a_numbered_pick(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(tmp_path, chunk_size=4)
    second = _write_plan(tmp_path, chunk_size=2)
    picks: list[str] = []

    def picker(label: str, default: str = "") -> str:
        picks.append(label)
        return "1"

    monkeypatch.setattr(operator_module, "prompt_text", picker)
    assert resolve_plan(state) is True
    assert state.plan_id == second
    assert any("Plan number" in pick for pick in picks)


def test_a_cancelled_pick_leaves_no_plan_established(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_plan(tmp_path, chunk_size=4)
    _write_plan(tmp_path, chunk_size=2)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "99")
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
    """v1's [A]ugment / [F]resh / [Q]uit offer, restored."""
    metadata = state.metadata()
    pointer = metadata.current_pointer
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text('{"snapshot_id": "abc123"}', encoding="utf-8")

    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "0")
    assert resolve_plan(state) is False
    assert "abc123" in capsys.readouterr().out


def test_the_working_plan_survives_across_menu_visits(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """State is the point: visiting the menu must not cost the operator a re-ask."""
    plan_id = _write_plan(tmp_path, chunk_size=2)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
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


def test_a_declined_refresh_publishes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: False)
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_refresh", seen.append)
    operator_module.refresh(WizardState())
    assert seen == []


# ------------------------------------------------------------------- delegation


def test_action_plan_records_the_plan_it_created(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        operator_module,
        "_ask_plan_options",
        lambda **_kwargs: plan_options(
            input_path=fixture_path("cik_sec_mini.csv"), artifacts_root=tmp_path
        ),
    )
    monkeypatch.setattr(operator_module, "cmd_plan", lambda options: None)
    operator_module.plan(state)
    assert state.plan_id == derive_plan_id(
        plan_options(
            input_path=fixture_path("cik_sec_mini.csv"), artifacts_root=tmp_path
        )
    )
    assert state.input_path.endswith("cik_sec_mini.csv")


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


def test_action_augment_requires_both_snapshot_ids(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        operator_module,
        "_ask_plan_options",
        lambda **_kwargs: plan_options(
            input_path=fixture_path("cik_sec_mini.csv"),
            artifacts_root=Path(state.artifacts_root),
        ),
    )
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: True)
    seen: list[dict] = []
    monkeypatch.setattr(
        operator_module, "cmd_augment", lambda options, **kwargs: seen.append(kwargs)
    )

    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    operator_module.augment(state)
    assert seen == []

    answers = iter(["base", "next", ""])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    operator_module.augment(state)
    assert seen[0]["base_snapshot_id"] == "base"
    assert seen[0]["new_snapshot_id"] == "next"


def test_augment_defaults_its_base_to_the_current_snapshot(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator augmenting usually means augmenting what is published."""
    pointer = state.metadata().current_pointer
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text('{"snapshot_id": "published-id"}', encoding="utf-8")

    monkeypatch.setattr(
        operator_module,
        "_ask_plan_options",
        lambda **_kwargs: plan_options(
            input_path=fixture_path("cik_sec_mini.csv"), artifacts_root=tmp_path
        ),
    )
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: True)
    seen: list[dict] = []
    monkeypatch.setattr(
        operator_module, "cmd_augment", lambda options, **kwargs: seen.append(kwargs)
    )

    def answers(label: str, default: str = "") -> str:
        # The base prompt offers the published snapshot as its default; only the
        # new snapshot id has to be typed.
        if "Base snapshot" in label:
            return default
        return "new-id" if "New snapshot" in label else default

    monkeypatch.setattr(operator_module, "prompt_text", answers)
    operator_module.augment(state)
    assert seen[0]["base_snapshot_id"] == "published-id"
    assert seen[0]["new_snapshot_id"] == "new-id"


def test_cancelled_answers_short_circuit_every_action(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(operator_module, "_ask_plan_options", lambda **_kwargs: None)
    monkeypatch.setattr(operator_module, "_ask_run_options", lambda *a, **k: None)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    monkeypatch.setattr(operator_module, "_ensure_plan", lambda _s: False)
    called: list[object] = []
    for command in COMMANDS.values():
        monkeypatch.setattr(
            operator_module,
            command.__name__,
            lambda *a, _n=command.__name__, **k: called.append(_n),
        )
    operator_module.plan(state)
    operator_module.status(state)
    operator_module.run(state)
    operator_module.merge(state)
    operator_module.augment(state)
    operator_module.export(state)
    operator_module.worker(state)
    operator_module.commands(state)
    assert called == []


def test_refresh_needs_no_reference_and_still_reaches_the_library(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refreshing is not scoped to a plan, so a blank answer is not a cancel."""
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: True)
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_refresh", seen.append)
    operator_module.refresh(state)
    assert seen == [None]


def test_compare_says_so_when_no_source_snapshot_exists(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    operator_module.compare(state)
    assert "no source snapshot published" in capsys.readouterr().out


# ----------------------------------------------------------------- command text


def test_commands_are_emitted_for_every_worker(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    state.plan_id = _write_plan(tmp_path, chunk_size=2)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    commands(state)
    out = capsys.readouterr().out
    assert f"--plan-id {state.plan_id}" in out
    assert out.count("run.py metadata worker") == 2
    assert "metadata export" in out
    assert "metadata merge" in out


def test_commands_default_to_a_destination_named_for_the_plan(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    state.plan_id = _write_plan(tmp_path, chunk_size=2)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    commands(state)
    assert f"distrib/{state.plan_id[:8]}" in capsys.readouterr().out


# ------------------------------------------------------------------- entrypoint


def test_main_dispatches_a_command_argument_to_the_cli(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "plan",
            "--input",
            str(fixture_path("cik_sec_mini.csv")),
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
    """v1 told the operator checkpoints are preserved; that is phase knowledge."""
    entered: list[str] = []

    def fake_menu(title, actions, exit_key="0", *, interrupted_message=None):
        entered.append(interrupted_message or "")
        # Drive only the status action; the others prompt for a plan this test
        # has not set up, and the point here is the interrupt message.
        for action in actions:
            if action.key == "2":
                try:
                    action.callback()
                except KeyboardInterrupt:
                    print(f"\n{interrupted_message or 'Action cancelled by user.'}")
        return 0

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
    assert "preserved" in capsys.readouterr().out
