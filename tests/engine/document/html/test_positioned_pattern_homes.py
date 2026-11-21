"""Pins for the positioned-html pattern homes (Wave 2B).
The table-open and whitespace-run recognizers live in
``foundation.text.patterns``; positioned binds them.
"""

from __future__ import annotations

from edgar_sec.engine.document.html import positioned
from edgar_sec.foundation.text.patterns import RE_TABLE_OPEN, RE_WHITESPACE


def test_bindings_are_the_homes() -> None:
    assert positioned._RE_TABLE_TAG is RE_TABLE_OPEN
    assert positioned._RE_WHITESPACE_RUN is RE_WHITESPACE


def test_table_open_verdicts() -> None:
    assert RE_TABLE_OPEN.search("<TABLE class='x'>") is not None
    assert RE_TABLE_OPEN.search("<table>") is not None
    assert RE_TABLE_OPEN.search("<tablex>") is None
    assert RE_TABLE_OPEN.search("<tab>") is None
