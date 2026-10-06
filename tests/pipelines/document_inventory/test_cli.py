"""Tests for the document_inventory CLI command surface.

The commands are placeholders; tests verify the parser, dispatch, exit codes, and
artifact resolution without exercising any pipeline logic.
"""

import argparse
import sys
from io import StringIO
from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.pipelines.document_inventory.cli import (
    _CommonOptions,
    _interactive,
    _resolve_common,
    build_parser,
    main,
)


def test_build_parser_has_subcommands() -> None:
    parser = build_parser()
    assert parser.parse_args(["cohort"]).command == "cohort"
    assert parser.parse_args(["index", "list"]).command == "index"
    assert parser.parse_args(["index", "replay", "--accession", "x"]).command == "index"
    assert parser.parse_args(["status"]).command == "status"
    assert parser.parse_args(["query"]).command == "query"
    assert parser.parse_args(["publish"]).command == "publish"


def test_build_parser_missing_command_fails() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_common_options_resolve_artifacts() -> None:
    args = argparse.Namespace(artifacts="/tmp/foo", workers=2, limit=100, json=True)
    options = _resolve_common(args)
    assert options.artifacts == Path("/tmp/foo")
    assert options.workers == 2
    assert options.limit == 100
    assert options.json is True


def test_common_options_empty_artifacts_is_none() -> None:
    args = argparse.Namespace(artifacts="", workers=None, limit=None, json=False)
    options = _resolve_common(args)
    assert options.artifacts is None


def test_resolve_common_missing_attr_defaults_limit() -> None:
    args = argparse.Namespace(artifacts="", workers=None, json=False)
    options = _resolve_common(args)
    assert options.limit is None


def test_main_cohort_not_implemented_returns_one() -> None:
    assert main(["cohort"]) == 1


def test_main_index_replay_not_implemented_returns_one() -> None:
    assert main(["index", "replay", "--accession", "0000123456-12-000001"]) == 1


def test_main_status_not_implemented_returns_one() -> None:
    assert main(["status"]) == 1


def test_main_query_not_implemented_returns_one() -> None:
    assert main(["query"]) == 1


def test_main_publish_not_implemented_returns_one() -> None:
    assert main(["publish"]) == 1


def test_main_invalid_command_returns_two() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["badcommand"])
    assert exc.value.code == 2


def test_resolve_paths_honors_artifacts_override() -> None:
    override = Path("/tmp/override")
    paths = resolve_paths(override)
    # resolve_paths treats the argument as repo_root; artifacts is derived beside it.
    assert paths.artifacts_root == override / ".artifacts"


def test_main_keyboard_interrupt_returns_130() -> None:
    import edgar_sec.pipelines.document_inventory.cli as cli

    def _broken_status(_options, _paths):
        raise KeyboardInterrupt

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli, "_cmd_status", _broken_status)
        assert main(["status"]) == 130


def test_main_help_shows_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for sub in ["cohort", "index", "status", "query", "publish"]:
        assert sub in out


def test_main_interactive_menu_exits_on_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import edgar_sec.pipelines.document_inventory.cli as cli

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sys.argv", ["inventory"])
        mp.setattr("builtins.input", lambda _: "0")
        mp.setattr(cli, "resolve_paths", lambda: Path("/tmp"))
        result = main(None)
    assert result == 0


def test_main_interactive_menu_runs_status(capsys: pytest.CaptureFixture[str]) -> None:
    import edgar_sec.pipelines.document_inventory.cli as cli

    inputs = iter(["4", "0"])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sys.argv", ["inventory"])
        mp.setattr("builtins.input", lambda _: next(inputs))
        mp.setattr(cli, "resolve_paths", lambda: Path("/tmp"))
        result = main(None)
    # Menu processes the status command (prints an error), then exits on "0".
    assert result == 0
    _, err = capsys.readouterr()
    assert "not implemented" in err
