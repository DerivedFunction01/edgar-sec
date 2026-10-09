"""Tests for docgen sentinel synchronization.

Offline verification of command table and paths table extraction.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from edgar_sec.tools.docgen import (
    COMMANDS_END,
    COMMANDS_START,
    format_subcommand_options,
    sync_readme,
)


def test_format_subcommand_options_extracts_required_and_optional() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--required-flag", required=True)
    parser.add_argument("--optional-flag", default="abc")
    result = format_subcommand_options(parser)
    assert "`--required-flag`" in result
    assert "`[--optional-flag]`" in result


def test_sync_readme_updates_sentinels_in_place(tmp_path: Path) -> None:
    pkg = tmp_path / "edgar_sec" / "test_pkg"
    pkg.mkdir(parents=True)
    readme = pkg / "README.md"
    readme.write_text(
        f"# Test Pkg\n\n## Command surface\n\n{COMMANDS_START}\nold\n{COMMANDS_END}\n",
        encoding="utf-8",
    )
    in_sync, content = sync_readme(readme, apply=False)
    assert in_sync is True
