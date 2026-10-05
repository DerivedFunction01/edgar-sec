"""The distributed lifecycle as copy-pasteable shell commands; every emitted line
is parsed by the real parser rather than checked for expected text.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync import worker_commands as renderer
from edgar_sec.pipelines.metadata_sync.cli import build_parser
from edgar_sec.pipelines.metadata_sync.paths import (
    resolve_metadata_paths,
    resolve_run_paths,
)
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from tests.support import compiled_cohort


@pytest.fixture()
def metadata(tmp_path: Path):
    return resolve_metadata_paths(tmp_path)


def _write_plan(tmp_path: Path, *, chunk_size: int = 2) -> str:
    cohort = compiled_cohort("cik_sec_mini.csv", tmp_path)
    plan = build_plan(cohort.roster, chunk_size=chunk_size)
    write_plan(plan, resolve_run_paths(plan.plan_id, tmp_path))
    return plan.plan_id


def _render(metadata, plan_id: str | None, monkeypatch, *answers: str) -> None:
    """Drive the renderer with a fixed plan and a scripted set of answers."""
    scripted = iter(answers)
    monkeypatch.setattr(
        renderer,
        "prompt_text",
        lambda label, default="": next(scripted) if answers else default,
    )
    renderer.render_worker_commands(metadata, lambda: plan_id)


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
    metadata, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A misread flag is invisible to substring assertions."""
    _render(metadata, _write_plan(tmp_path, chunk_size=1), monkeypatch)
    out = capsys.readouterr().out

    emitted = _emitted_commands(out)
    assert emitted, "the renderer printed no commands"
    parser = build_parser()
    for argv in emitted:
        body = argv[argv.index("metadata") + 1 :]
        parsed = parser.parse_args(body)
        assert parsed.func is not None, body


def test_emitted_commands_describe_the_whole_distributed_lifecycle(
    metadata, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Import is the step that adopts returned chunks; omitting it merges nothing."""
    _render(metadata, _write_plan(tmp_path, chunk_size=1), monkeypatch)
    names = [name for name, _ in _emitted_subcommands(capsys.readouterr().out)]
    assert names == ["export", "worker", "worker", "import", "import", "merge"]


def test_emitted_worker_commands_name_the_real_bundles(
    metadata, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Worker ids come from the same division ``export`` will emit."""
    _render(
        metadata, _write_plan(tmp_path, chunk_size=1), monkeypatch, "2", "distrib/x"
    )
    pairs = _emitted_subcommands(capsys.readouterr().out)

    workers = [options for name, options in pairs if name == "worker"]
    bundles = [options["--bundle"] for options in workers]
    assert bundles == ["distrib/x/worker-00", "distrib/x/worker-01"]
    exports = next(options for name, options in pairs if name == "export")
    assert exports["--worker-count"] == "2"
    # Each worker's import names the same bundle its worker command does.
    imports = [options for name, options in pairs if name == "import"]
    assert [options["--source"] for options in imports] == bundles


def test_emitted_commands_omit_workers_with_no_chunk(
    metadata, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Empty assignments are skipped, so no command names a bundle export never makes."""
    _render(
        metadata, _write_plan(tmp_path, chunk_size=4), monkeypatch, "8", "distrib/s"
    )
    pairs = _emitted_subcommands(capsys.readouterr().out)
    assert [name for name, _ in pairs].count("worker") == 1


def test_emitted_commands_survive_a_destination_with_spaces(
    metadata, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A copy-pasteable command that breaks on a path with a space is not one."""
    _render(
        metadata,
        _write_plan(tmp_path, chunk_size=1),
        monkeypatch,
        "2",
        "distrib/q3 run",
    )
    pairs = _emitted_subcommands(capsys.readouterr().out)

    export = next(options for name, options in pairs if name == "export")
    assert export["--destination"] == "distrib/q3 run"
    for name, options in pairs:
        if name in {"worker", "import"}:
            key = "--bundle" if name == "worker" else "--source"
            assert options[key].startswith("distrib/q3 run/")


def test_commands_refuse_to_render_for_an_unreadable_plan(
    metadata, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Commands for an unloadable plan would point workers at no bundle."""
    _render(metadata, "does-not-exist", monkeypatch)
    out = capsys.readouterr().out
    assert "unreadable" in out
    assert _emitted_commands(out) == []


def test_an_unresolved_plan_prints_nothing(
    metadata, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A cancelled pick must not fall through to a default plan."""
    _render(metadata, None, monkeypatch)
    assert _emitted_commands(capsys.readouterr().out) == []


def test_a_blank_destination_stops_before_printing(
    metadata, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _render(metadata, _write_plan(tmp_path, chunk_size=1), monkeypatch, "2", "")
    assert _emitted_commands(capsys.readouterr().out) == []


def test_a_destination_is_offered_defaulted_to_the_plan(
    metadata, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The default names the plan, so two exports do not overwrite each other."""
    plan_id = _write_plan(tmp_path, chunk_size=1)
    _render(metadata, plan_id, monkeypatch)
    export = next(
        options
        for name, options in _emitted_subcommands(capsys.readouterr().out)
        if name == "export"
    )
    assert export["--destination"] == f"distrib/{plan_id[:8]}"
