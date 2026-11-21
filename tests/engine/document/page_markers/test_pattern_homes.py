"""Pins for the page-markers pattern homes (Wave 2B).
The whitespace-run and table-span recognizers live in
``foundation.text.patterns``; the page-marker modules bind them.
"""

from __future__ import annotations

from edgar_sec.engine.document.page_markers import (
    artifacts,
    candidates,
    content_lines,
    policy,
    templates,
)
from edgar_sec.foundation.text.patterns import RE_TABLE_SPAN, RE_WHITESPACE


def test_whitespace_bindings_are_the_home() -> None:
    assert artifacts._WHITESPACE_RE is RE_WHITESPACE
    assert candidates._COLLAPSE_WS_RE is RE_WHITESPACE
    assert content_lines._WHITESPACE_RE is RE_WHITESPACE
    assert templates._WHITESPACE_RE is RE_WHITESPACE


def test_table_span_binding_is_the_home() -> None:
    assert policy._TAGGED_TABLE is RE_TABLE_SPAN


def test_whitespace_verdicts() -> None:
    assert RE_WHITESPACE.sub(" ", "a \t\n  b") == "a b"
    assert RE_WHITESPACE.split("a  b\tc") == ["a", "b", "c"]


def test_table_span_verdicts() -> None:
    match = RE_TABLE_SPAN.search("x<TABLE>\nbody\n</TABLE>y")
    assert match is not None
    assert match.group(0) == "<TABLE>\nbody\n</TABLE>"
    assert RE_TABLE_SPAN.search("<table>unterminated") is None
