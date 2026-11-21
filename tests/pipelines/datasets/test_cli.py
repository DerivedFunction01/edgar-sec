"""CLI surface: parser shape and offline status/verify commands."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.pipelines.datasets.cli import build_parser, main


def test_parser_names_every_command() -> None:
    parser = build_parser()
    actions = [
        action
        for action in parser._subparsers._group_actions  # noqa: SLF001
    ]
    choices = actions[0].choices
    assert {"import", "population", "publish", "verify", "status", "dag"} <= set(
        choices
    )


def test_status_and_verify_on_an_empty_root(tmp_path: Path) -> None:
    assert main(["status", "--artifacts", str(tmp_path)]) == 0
    assert main(["verify", "--artifacts", str(tmp_path)]) == 0


def test_import_requires_a_vintage() -> None:
    parser = build_parser()
    try:
        parser.parse_args(["import", "--set", "bdc"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("import without --vintage parsed successfully")
