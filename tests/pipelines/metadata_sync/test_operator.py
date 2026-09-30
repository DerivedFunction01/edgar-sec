"""Operator wizard tests: state, discovery, and command delegation.

Two failure classes are guarded here. The first is a binding that drifts from
the command surface -- an action pointing at a command that no longer reads an
argument the wizard sets -- which would fail only inside an interactive session
nobody runs in CI. The second is the regression this pass restored: a wizard that
asks for a plan id it was never shown, and silently does nothing when the answer
is blank. Every action must either work, ask, or say why it cannot.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync import operator as operator_module
from edgar_sec.pipelines.metadata_sync.assignment import divide_chunks
from edgar_sec.pipelines.metadata_sync.cli import (
    build_parser,
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
from edgar_sec.pipelines.metadata_sync.discovery import current_snapshot_id
from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.merger import publish_current_snapshot
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
from edgar_sec.pipelines.metadata_sync.roster import roster_from_manifest
from edgar_sec.pipelines.metadata_sync.source_registry import SOURCE_NAME
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
        "c",
    ]


def test_pointer_selection_and_command_rendering_have_distinct_keys() -> None:
    """v1 used ``p`` for the pointer; reusing it for commands lost that action."""
    labels = {action.key: action.label for action in build_operator_menu()}
    assert "current" in labels["p"].lower()
    assert "worker commands" in labels["c"].lower()


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
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    assert _ask_plan_options(state, with_limit=True) is None


def test_ask_plan_options_uses_registered_defaults(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "17")
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    options = _ask_plan_options(state)
    assert options is not None
    assert options.input_path is not None
    assert options.input_path.name == Path(DEFAULT_INPUT).name
    assert options.chunk_size == 17


def test_ask_plan_options_records_a_limit(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter([str(fixture_path("cik_sec_mini.csv")), "1000", "3"])
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


def test_session_header_names_the_plan_and_the_published_snapshot(
    state: WizardState, tmp_path: Path
) -> None:
    """The header is what makes the session's target visible without running status."""
    state.plan_id = _write_plan(tmp_path, chunk_size=2)
    pointer = state.metadata().current_pointer
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text('{"snapshot_id": "abc123"}', encoding="utf-8")

    header = render_session_header(state)
    assert state.plan_id in header
    assert "abc123" in header


def test_session_header_admits_an_unresolved_session(state: WizardState) -> None:
    """A blank line where a plan id used to be reads as a broken menu."""
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
        lambda *a, **k: plan_options(
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


def test_action_augment_needs_only_a_base_snapshot_id(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blank new-snapshot id now means "derive it", not "cancel".

    Requiring a hand-typed id was the one Phase 1 identity that was not derived
    from its content, while ``merge`` in the same pipeline already defaulted to
    the plan id. Cancelling now requires declining the fetch instead.
    """
    monkeypatch.setattr(
        operator_module,
        "_ask_plan_options",
        lambda *a, **k: plan_options(
            input_path=fixture_path("cik_sec_mini.csv"),
            artifacts_root=Path(state.artifacts_root),
        ),
    )
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: True)
    seen: list[dict] = []
    monkeypatch.setattr(
        operator_module, "cmd_augment", lambda options, **kwargs: seen.append(kwargs)
    )

    def answers_for(label: str, default: str = "") -> str:
        if "Base snapshot" in label:
            return "base"
        if "New snapshot" in label:
            return ""
        return default

    monkeypatch.setattr(operator_module, "prompt_text", answers_for)
    operator_module.augment(state)
    assert seen[0]["base_snapshot_id"] == "base"
    assert seen[0]["new_snapshot_id"] == ""


def test_action_augment_still_cancels_without_a_base(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        operator_module,
        "_ask_plan_options",
        lambda *a, **k: plan_options(
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


def test_a_declined_augment_fetches_nothing(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        operator_module,
        "_ask_plan_options",
        lambda *a, **k: plan_options(
            input_path=fixture_path("cik_sec_mini.csv"),
            artifacts_root=Path(state.artifacts_root),
        ),
    )
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: False)
    seen: list[dict] = []
    monkeypatch.setattr(
        operator_module, "cmd_augment", lambda options, **kwargs: seen.append(kwargs)
    )

    def answers(label: str, default: str = "") -> str:
        if "Base snapshot" in label:
            return "base"
        return default

    monkeypatch.setattr(operator_module, "prompt_text", answers)
    operator_module.augment(state)
    assert seen == []
    assert "nothing was fetched" in capsys.readouterr().out


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
        lambda *a, **k: plan_options(
            input_path=fixture_path("cik_sec_mini.csv"), artifacts_root=tmp_path
        ),
    )
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: True)
    seen: list[dict] = []
    monkeypatch.setattr(
        operator_module, "cmd_augment", lambda options, **kwargs: seen.append(kwargs)
    )

    def answers(label: str, default: str = "") -> str:
        # The base prompt offers the published snapshot as its default. The new
        # snapshot id is left blank so the pipeline derives it.
        if "Base snapshot" in label:
            return default
        if "New snapshot" in label:
            return ""
        return default

    monkeypatch.setattr(operator_module, "prompt_text", answers)
    operator_module.augment(state)
    assert seen[0]["base_snapshot_id"] == "published-id"
    assert seen[0]["new_snapshot_id"] == ""


def test_cancelled_answers_short_circuit_every_action(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(operator_module, "_ask_plan_options", lambda *a, **k: None)
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


# ------------------------------------------------------------- emitted commands


def _emitted_commands(out: str) -> list[list[str]]:
    """Every ``python run.py metadata ...`` line, tokenized the way a shell would."""
    return [
        shlex.split(line.strip())
        for line in out.splitlines()
        if line.strip().startswith("python run.py metadata")
    ]


def _emitted_subcommands(out: str) -> list[tuple[str, dict[str, str]]]:
    parsed: list[tuple[str, dict[str, str]]] = []
    for argv in _emitted_commands(out):
        body = argv[argv.index("metadata") + 1 :]
        parsed.append((body[0], _options_of(body)))
    return parsed


def _options_of(body: list[str]) -> dict[str, str]:
    options: dict[str, str] = {}
    key = ""
    for token in body[1:]:
        if token.startswith("--"):
            key = token
            options[key] = ""
        elif key:
            options[key] = token
    return options


def test_every_emitted_command_is_accepted_by_the_parser(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The emitted text must parse, not merely contain the right substrings.

    Both flag mistakes in this renderer were invisible to substring assertions: a
    ``--workers`` that the parser read as a different argument, and a ``--worker-id``
    that does not exist at all. Round-tripping each line through the real parser is
    what makes that class of defect fail here instead of on a remote machine.
    """
    state.plan_id = _write_plan(tmp_path, chunk_size=1)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    commands(state)
    out = capsys.readouterr().out

    emitted = _emitted_commands(out)
    assert emitted, "the renderer printed no commands"
    parser = build_parser()
    for argv in emitted:
        body = argv[argv.index("metadata") + 1 :]
        parsed = parser.parse_args(body)
        assert parsed.func is not None, body


def test_emitted_commands_describe_the_whole_distributed_lifecycle(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Import is the step that adopts returned chunks; omitting it merges nothing."""
    state.plan_id = _write_plan(tmp_path, chunk_size=1)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    commands(state)
    subcommands = [name for name, _ in _emitted_subcommands(capsys.readouterr().out)]

    assert subcommands[0] == "export"
    assert subcommands[-1] == "merge"
    assert "worker" in subcommands
    # One import per worker, and every import precedes the merge.
    assert subcommands.count("import") == subcommands.count("worker")
    assert subcommands.index("import") < subcommands.index("merge")


def test_emitted_worker_commands_name_the_real_bundles(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Bundle names and worker ids come from the same division export performs."""
    state.plan_id = _write_plan(tmp_path, chunk_size=1)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    commands(state)
    pairs = _emitted_subcommands(capsys.readouterr().out)

    export = next(options for name, options in pairs if name == "export")
    expected = {
        worker_id
        for worker_id, chunk_ids in divide_chunks(
            4, int(export["--worker-count"])
        ).items()
        if chunk_ids
    }
    for name, options in pairs:
        if name != "worker":
            continue
        worker_id = options["--worker"]
        assert worker_id in expected
        assert Path(options["--bundle"]).name == worker_id


def test_emitted_commands_omit_workers_with_no_chunk(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """More workers than chunks would otherwise print a command for a bundle
    ``export`` never creates, because empty assignments are skipped."""
    state.plan_id = _write_plan(tmp_path, chunk_size=4)
    answers = iter(["8", "distrib/spread"])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    commands(state)
    pairs = _emitted_subcommands(capsys.readouterr().out)
    assert [name for name, _ in pairs].count("worker") == 1


def test_emitted_commands_survive_a_destination_with_spaces(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A copy-pasteable command that breaks on a path with a space is not one."""
    state.plan_id = _write_plan(tmp_path, chunk_size=1)
    answers = iter(["2", "distrib/q3 run"])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    commands(state)
    pairs = _emitted_subcommands(capsys.readouterr().out)

    export = next(options for name, options in pairs if name == "export")
    assert export["--destination"] == "distrib/q3 run"
    for name, options in pairs:
        if name in {"worker", "import"}:
            assert options["--bundle" if name == "worker" else "--source"].startswith(
                "distrib/q3 run/"
            )


def test_commands_refuse_to_render_for_an_unreadable_plan(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Emitting commands for a plan this build cannot load would point workers at
    a bundle that does not exist."""
    state.plan_id = "does-not-exist"
    monkeypatch.setattr(operator_module, "_ensure_plan", lambda _s: True)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    commands(state)
    out = capsys.readouterr().out
    assert "unreadable" in out
    assert _emitted_commands(out) == []


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


def test_compare_resolves_the_source_manifest_from_its_snapshot_id(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The manifest has no ``manifest_path`` field; reading one resolved to the CWD.

    A source manifest describes the listing it published and carries no path to
    itself, so the comparison was handed a directory and failed. The path is
    derived from the selected id instead.
    """
    metadata = state.metadata()
    manifest_path = metadata.source_manifest_file(SOURCE_NAME, "src-1")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        '{"snapshot_id": "src-1", "manifest_kind": "x"}', encoding="utf-8"
    )

    monkeypatch.setattr(
        operator_module, "list_snapshots", lambda _paths: [{"snapshot_id": "src-1"}]
    )
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    seen: list[Path] = []
    monkeypatch.setattr(
        operator_module,
        "cmd_compare",
        lambda options, **kwargs: seen.append(kwargs["source_manifest"]),
    )
    operator_module.compare(state)
    assert seen == [manifest_path]
    assert seen[0].is_file()


# ----------------------------------------------------------------- command text


def test_commands_default_to_a_destination_named_for_the_plan(
    state: WizardState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    state.plan_id = _write_plan(tmp_path, chunk_size=2)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    commands(state)
    assert f"distrib/{state.plan_id[:8]}" in capsys.readouterr().out


# ----------------------------------------------------------------- the pointer


def test_selecting_a_snapshot_moves_the_current_pointer(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A merge can only advance the pointer; this is what moves it back."""
    metadata = state.metadata()
    for snapshot_id in ("newer", "older"):
        manifest = metadata.snapshot_manifest(snapshot_id)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"snapshot_id": snapshot_id, "row_count": 7}), encoding="utf-8"
        )
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
    manifest = metadata.snapshot_manifest("only")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"snapshot_id": "only"}', encoding="utf-8")
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
    """Pointing at a snapshot with no manifest is worse than a stale pointer."""
    metadata = state.metadata()
    known = metadata.snapshot_manifest("known")
    known.parent.mkdir(parents=True, exist_ok=True)
    known.write_text('{"snapshot_id": "known"}', encoding="utf-8")
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

    def fake_menu(
        title, actions, exit_key="0", *, interrupted_message=None, before_menu=None
    ):
        entered.append(interrupted_message or "")
        if before_menu is not None:
            # The entrypoint must pass the session header through, or the menu
            # shows no indication of what the session is pointed at.
            rendered.append(before_menu() or "")
        # Drive only the status action; the others prompt for a plan this test
        # has not set up, and the point here is the interrupt message.
        for action in actions:
            if action.key == "2":
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
