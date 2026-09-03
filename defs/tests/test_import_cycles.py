"""Regression tests for the shared text/table import graph."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _fresh_import(statement: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", statement],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_table_tokens_can_initialize_before_text_reflow() -> None:
    _fresh_import("import defs.tables.tokens")


def test_reflow_can_be_imported_through_text_package() -> None:
    _fresh_import("from defs.text import reflow_ascii")


def test_reflow_direct_import_is_order_independent() -> None:
    _fresh_import("import defs.text.reflow")
