import runpy

import pytest

import run
from edgar_sec.foundation.runtime.interactive import MenuSeparator
from run import ENTRIES


def test_inventory_launcher_routes_through_discovery_operator() -> None:
    entry = next(item for item in ENTRIES if item.id == "inventory")
    assert entry.module == "edgar_sec.pipelines.document_inventory.operator"


def test_document_planning_launcher_routes_through_operator() -> None:
    entry = next(item for item in ENTRIES if item.id == "planning")
    assert entry.module == "edgar_sec.pipelines.document_planning.operator"


def test_document_acquisition_launcher_routes_through_operator() -> None:
    entry = next(item for item in ENTRIES if item.id == "acquisition")
    assert entry.module == "edgar_sec.pipelines.document_acquisition.operator"


def test_dag_launcher_routes_through_dag_operator() -> None:
    entry = next(item for item in ENTRIES if item.id == "dag")
    assert entry.module == "edgar_sec.infra.storage.dag.operator"


def test_cohort_launcher_routes_through_cohort_cli() -> None:
    entry = next(item for item in ENTRIES if item.id == "cohort")
    assert entry.module == "edgar_sec.pipelines.cohort.cli"


def _drive_menu(monkeypatch: pytest.MonkeyPatch, answers: list[str], launch) -> int:
    remaining = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(remaining))
    monkeypatch.setattr(runpy, "run_module", launch)
    return run._menu()


def test_menu_groups_entries_under_separators() -> None:
    separators = [
        item.title for item in run._MENU_ITEMS if isinstance(item, MenuSeparator)
    ]
    assert separators == ["Pipelines", "Apps & Consoles"]
    assert [entry.id for entry in ENTRIES] == [
        "cohort",
        "metadata",
        "feeds",
        "datasets",
        "filing-catalog",
        "inventory",
        "planning",
        "acquisition",
        "xbrl",
        "viewer",
        "fetch",
        "dag",
    ]


def test_menu_survives_raising_entry_and_runs_next(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def launch(module: str, run_name: str | None = None, alter_sys: bool = False):
        calls.append(module)
        if len(calls) == 1:
            raise RuntimeError("boom")

    assert _drive_menu(monkeypatch, ["1", "2", "0"], launch) == 0
    assert calls == [ENTRIES[0].module, ENTRIES[1].module]
    assert "Error executing action 'Cohort Management': RuntimeError('boom')" in (
        capsys.readouterr().out
    )


def test_menu_survives_system_exit_and_clean_exit_returns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outcomes: list[BaseException | None] = [SystemExit(2), SystemExit(0), None]
    calls: list[str] = []

    def launch(module: str, run_name: str | None = None, alter_sys: bool = False):
        calls.append(module)
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome

    assert _drive_menu(monkeypatch, ["1", "1", "1", "0"], launch) == 0
    assert len(calls) == 3
    out = capsys.readouterr().out
    assert "Error executing action 'Cohort Management': SystemExit(2)" in out
    assert out.count("Error executing action") == 1


def test_menu_survives_keyboard_interrupt_entry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def launch(module: str, run_name: str | None = None, alter_sys: bool = False):
        raise KeyboardInterrupt

    assert _drive_menu(monkeypatch, ["1", "0"], launch) == 0
    assert "Action cancelled by user." in capsys.readouterr().out


def test_menu_eof_exits_without_launching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_input(_prompt: str = "") -> str:
        raise EOFError

    calls: list[str] = []
    monkeypatch.setattr("builtins.input", no_input)
    monkeypatch.setattr(runpy, "run_module", lambda *a, **k: calls.append("x"))
    assert run._menu() == 0
    assert calls == []


def test_help_names_entries_and_forwarding_rule(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run.main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "Usage: python run.py" in out
    assert "forwarded to the entry unchanged" in out
    assert "LauncherEntry" not in out
    for entry in ENTRIES:
        assert entry.id in out
