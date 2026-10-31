from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.pipelines.cohort.ingestion import ingest_file_to_cohort
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.pipelines.cohort.workspace import CohortWorkspace
from edgar_sec.infra.storage.object_store.store import ObjectStore
from edgar_sec.pipelines.cohort.repl import run_repl


def _context(tmp_path: Path):
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    store = ObjectStore(paths.catalog_file)
    store.initialize_schema()
    store.touch_session("global")
    store.set_active_session("global")
    source = tmp_path / "members.csv"
    source.write_text("cik,name\n320193,Apple\n789019,Microsoft\n", encoding="utf-8")
    cohort = ingest_file_to_cohort(
        source, catalog=catalog, paths=paths, name="members"
    ).cohort
    return paths, catalog, store, cohort


def test_repl_reuses_workspace_parser_without_python_eval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths, catalog, store, cohort = _context(tmp_path)
    other_file = tmp_path / "other.csv"
    other_file.write_text("cik,name\n789019,Microsoft\n", encoding="utf-8")
    other = ingest_file_to_cohort(
        other_file, catalog=catalog, paths=paths, name="other"
    ).cohort
    lines = iter(
        (
            'bind A "members"',
            f"bind B {other.cohort_id}",
            "let only_a = A - B",
            "diff A B",
            "vars",
            "peek only_a 1",
            'save only_a "subset name" --tags test,interactive',
            "drop B",
            "clear",
            "exit",
        )
    )
    monkeypatch.setattr(
        builtins,
        "eval",
        lambda *_args, **_kwargs: pytest.fail("REPL must not call eval"),
    )

    assert run_repl(paths, catalog, store, input_fn=lambda _prompt: next(lines)) == 0

    output = capsys.readouterr().out
    assert "only_a ->" in output
    assert "Workspace Variables" in output
    assert "Cohort Diff" in output
    assert "Preview: only_a" in output
    assert "saved " in output
    saved = catalog.resolve_cohort_identifier("subset name")
    assert saved.row_count == 1
    assert saved.tags == ("interactive", "test")
    assert store.get_active_session() == "global"
    assert not any(session.startswith("repl_") for session in store.list_sessions())


def test_repl_use_keeps_persistent_session_and_does_not_switch_global(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths, catalog, store, cohort = _context(tmp_path)
    persistent = CohortWorkspace(
        paths, catalog=catalog, store=store, session_id="saved"
    )
    persistent.bind_alias("P", cohort.cohort_id)
    lines = iter(("use saved", "vars", "exit"))

    assert run_repl(paths, catalog, store, input_fn=lambda _prompt: next(lines)) == 0

    assert "P" in capsys.readouterr().out
    assert store.get_active_session() == "global"
    assert store.list_aliases("saved") == {"P": cohort.cohort_id}
    assert "saved" in store.list_sessions()
    assert not any(session.startswith("repl_") for session in store.list_sessions())


def test_repl_reports_command_errors_and_cleans_up_on_interrupt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths, catalog, store, _cohort = _context(tmp_path)
    lines = iter(("unknown-command", "exit"))
    run_repl(paths, catalog, store, input_fn=lambda _prompt: next(lines))
    assert "unknown command" in capsys.readouterr().out

    def interrupt(_prompt: str) -> str:
        raise KeyboardInterrupt

    assert run_repl(paths, catalog, store, input_fn=interrupt) == 0
    assert store.get_active_session() == "global"
    assert not any(session.startswith("repl_") for session in store.list_sessions())

    def end_of_file(_prompt: str) -> str:
        raise EOFError

    assert run_repl(paths, catalog, store, input_fn=end_of_file) == 0
    assert store.get_active_session() == "global"
    assert not any(session.startswith("repl_") for session in store.list_sessions())
