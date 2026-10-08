"""Operator wizard: state, discovery, and command delegation; a binding that
drifts from the command surface fails only in an interactive session.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.metadata_sync import augment_flow
from edgar_sec.pipelines.metadata_sync import operator as operator_module
from edgar_sec.pipelines.metadata_sync.cli import (
    cmd_compare,
    cmd_family_index,
    cmd_merge,
    cmd_plan,
    cmd_refresh,
    cmd_run,
    cmd_status,
)
from edgar_sec.pipelines.metadata_sync.discovery import current_snapshot_id
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
    confirm_network,
    family_index,
    main,
    render_plan_header,
    render_session_header,
    resolve_plan,
)
from edgar_sec.pipelines.metadata_sync.options import (
    PlanOptions,
    derive_plan_id,
    plan_options,
    run_options,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from edgar_sec.pipelines.metadata_sync.source_registry import (
    SOURCE_NAME,
    SOURCE_UNIVERSE_NAME,
)
from tests.support import fixture_cohort, fixture_path, published_universe

COMMANDS = {
    "plan": cmd_plan,
    "status": cmd_status,
    "run": cmd_run,
    "merge": cmd_merge,
    "refresh": cmd_refresh,
    "compare": cmd_compare,
}


@pytest.fixture()
def state(tmp_path: Path) -> WizardState:
    return WizardState(artifacts_root=str(tmp_path))


def _write_plan(tmp_path: Path, *, chunk_size: int = 2) -> str:
    plan = build_plan(fixture_cohort("cik_sec_mini.csv").roster, chunk_size=chunk_size)
    write_plan(plan, resolve_run_paths(plan.plan_id, tmp_path))
    return plan.plan_id


# ------------------------------------------------------------------------ menu


def test_menu_covers_the_whole_lifecycle() -> None:
    menu = build_operator_menu()
    labels = {action.key: action.label for action in menu}
    assert "d" in labels and "distribution" in labels["d"].lower()
    assert "p" in labels and (
        "dag" in labels["p"].lower() or "snapshot" in labels["p"].lower()
    )
    assert "f" in labels and "famil" in labels["f"].lower()
    assert any("Plan" in label for label in labels.values())
    assert any("Augment" in label for label in labels.values())
    assert MENU_TITLE.startswith("Metadata Sync")


def test_every_menu_action_binds_to_a_shared_command() -> None:
    """A menu entry that points nowhere is how a command becomes dead surface."""
    for action in build_operator_menu():
        assert action.callback.__name__ == "<lambda>"
        assert callable(action.callback)


def test_the_family_index_action_explains_a_missing_universe(
    tmp_path: Path, capsys
) -> None:
    """It must not crash the menu; it says which earlier step is missing."""
    state = WizardState()
    state.artifacts_root = str(tmp_path)
    family_index(state)
    out = capsys.readouterr().out
    assert "cik_lookup" in out
    assert "Refresh external source" in out


def test_the_family_index_action_builds_against_a_published_universe(
    tmp_path: Path, capsys
) -> None:
    published_universe(tmp_path)
    state = WizardState()
    state.artifacts_root = str(tmp_path)
    family_index(state)
    out = capsys.readouterr().out
    assert "Family Index Published" in out
    assert "family_index_id" in out


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
    monkeypatch.setattr(operator_module, "_ask_cohort_source", lambda _state: None)
    assert _ask_plan_options(state, with_limit=True) is None


def test_ask_plan_options_uses_registered_defaults(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "17")
    monkeypatch.setattr(
        operator_module,
        "_ask_cohort_source",
        lambda _state: plan_options(input_path=DEFAULT_INPUT),
    )
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    options = _ask_plan_options(state)
    assert options is not None
    assert options.input_path is not None
    assert options.input_path.name == Path(DEFAULT_INPUT).name
    assert options.chunk_size == 17


def test_ask_plan_options_records_a_limit(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        operator_module,
        "_ask_cohort_source",
        lambda _state: plan_options(input_path=fixture_path("cik_sec_mini.csv")),
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


def test_a_declined_refresh_publishes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: False)
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_refresh", seen.append)
    operator_module.refresh(WizardState())
    assert seen == []


def _publish_source(state: WizardState, snapshot_id: str) -> None:
    """Write a source snapshot manifest so the wizard's listing finds a real one."""
    path = state.metadata().source_manifest_file(SOURCE_NAME, snapshot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "manifest_kind": "metadata_source_snapshot",
                "source": SOURCE_NAME,
                "snapshot_id": snapshot_id,
                "retrieved_at": "2026-01-01T00:00:00Z",
                "unique_cik_count": 2,
                "listing_row_count": 2,
            }
        ),
        encoding="utf-8",
    )


def _forbid_artifacts_prompts(
    monkeypatch: pytest.MonkeyPatch, asked: list[str]
) -> None:
    """Failing on the label, not on a count, catches a re-added root prompt."""

    def stub(label: str, default: str = "") -> str:
        asked.append(label)
        if "rtifact" in label:
            pytest.fail(f"the wizard asked for the artifacts root: {label!r}")
        return default

    monkeypatch.setattr(operator_module, "prompt_text", stub)


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


# ------------------------------------------------------- refresh and compare


def test_refresh_needs_no_reference_and_still_reaches_the_library(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refreshing is not scoped to a plan, so a blank answer is not a cancel."""
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default="": "")
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: True)
    seen: list[tuple[object, str]] = []
    monkeypatch.setattr(
        operator_module,
        "cmd_refresh",
        lambda root, *, source: seen.append((root, source)),
    )
    operator_module.refresh(state)
    assert seen == [(state.metadata().artifacts_root, SOURCE_NAME)]


def test_refresh_targets_the_session_artifacts_root_without_asking(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project-default root would publish outside the tree the session reads."""
    asked: list[str] = []
    refreshed: list[tuple[Path | None, str]] = []
    _forbid_artifacts_prompts(monkeypatch, asked)
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: True)
    monkeypatch.setattr(
        operator_module,
        "cmd_refresh",
        lambda root, *, source: refreshed.append((root, source)),
    )

    operator_module.refresh(state)

    assert refreshed == [(state.metadata().artifacts_root, SOURCE_NAME)]
    # Asking which source is expected; the helper already fails on any root prompt.
    assert asked == ["Source number"]


def test_compare_targets_the_session_artifacts_root(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project-default root would find no source snapshot and refuse."""
    _publish_source(state, "src-1")
    asked: list[str] = []
    seen: list[PlanOptions] = []
    _forbid_artifacts_prompts(monkeypatch, asked)
    monkeypatch.setattr(
        operator_module, "cmd_compare", lambda options, **kw: seen.append(options)
    )

    operator_module.compare(state)

    assert len(seen) == 1
    assert seen[0].artifacts_root == state.metadata().artifacts_root
    assert asked, "compare still prompts for its own inputs"


def test_compare_says_so_when_no_source_snapshot_exists(
    state: WizardState, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default="": default
    )
    operator_module.compare(state)
    assert "no source snapshot published" in capsys.readouterr().out


def test_compare_resolves_the_source_manifest_from_its_snapshot_id(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The manifest carries no path to itself, so the id derives it."""
    metadata = state.metadata()
    manifest_path = metadata.source_manifest_file(SOURCE_NAME, "src-1")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        '{"snapshot_id": "src-1", "manifest_kind": "x"}', encoding="utf-8"
    )
    monkeypatch.setattr(
        operator_module,
        "list_source_snapshots",
        lambda _paths: [
            {
                "snapshot_id": "src-1",
                "manifest_path": str(manifest_path),
                "retrieved_at": "2026-09-30T00:00:00Z",
                "unique_cik_count": 2,
                "listing_row_count": 2,
                "readable": True,
                "readable_reason": "",
            }
        ],
    )
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default="": default
    )
    seen: list[Path] = []
    monkeypatch.setattr(
        operator_module,
        "cmd_compare",
        lambda options, **kwargs: seen.append(kwargs["source_manifest"]),
    )
    operator_module.compare(state)
    assert seen == [manifest_path]
    assert seen[0].is_file()


def test_compare_lists_source_snapshots_not_published_metadata_snapshots(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A metadata snapshot id is never a source snapshot id."""
    _write_plan(Path(state.artifacts_root))
    monkeypatch.setattr(operator_module, "list_source_snapshots", lambda _paths: [])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default="": default
    )
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_compare", lambda *a, **k: seen.append(k))
    operator_module.compare(state)
    assert seen == []


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


def test_refresh_can_publish_the_universe_index(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The universe was reachable only from the CLI; the menu must reach it too."""
    seen: list[tuple[object, str]] = []
    monkeypatch.setattr(
        operator_module,
        "prompt_text",
        lambda label, default="": "2" if label == "Source number" else default,
    )
    monkeypatch.setattr(operator_module, "confirm_network", lambda *a, **k: True)
    monkeypatch.setattr(
        operator_module,
        "cmd_refresh",
        lambda root, *, source: seen.append((root, source)),
    )

    operator_module.refresh(state)

    assert seen == [(state.metadata().artifacts_root, SOURCE_UNIVERSE_NAME)]


def test_refresh_names_the_source_in_its_consent(
    state: WizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Network confirmation must identify the selected source."""
    prompts: list[str] = []
    monkeypatch.setattr(
        operator_module,
        "prompt_text",
        lambda label, default="": "2" if label == "Source number" else default,
    )
    monkeypatch.setattr(
        operator_module,
        "confirm_network",
        lambda prompt="": prompts.append(prompt) or True,
    )
    monkeypatch.setattr(operator_module, "cmd_refresh", lambda root, *, source: None)

    operator_module.refresh(state)

    assert any(SOURCE_UNIVERSE_NAME in text for text in prompts)
