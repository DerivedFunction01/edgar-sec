"""Divergence pins for the ownership ASCII table-tag pair (Wave 2B).
The pair stands uncollapsed: its capture-group span is narrower than
the foundation span home, and the flip cases below price the delta.
"""

from __future__ import annotations

from edgar_sec.engine.forms.ownership import ascii_shape, ascii_tables
from edgar_sec.foundation.text.patterns import RE_TABLE_SPAN


def test_pair_shares_one_pattern() -> None:
    assert ascii_shape._TABLE_TAG_RE.pattern == ascii_tables._TABLE_TAG_RE.pattern
    assert ascii_shape._TABLE_TAG_RE.flags == ascii_tables._TABLE_TAG_RE.flags


def test_local_verdict_returns_inner_text() -> None:
    assert ascii_shape._TABLE_TAG_RE.findall("<TABLE>inner</TABLE>") == ["inner"]
    assert ascii_tables._TABLE_TAG_RE.findall("<TABLE>inner</TABLE>") == ["inner"]


def test_flip_case_attribute_bearing_open_tag() -> None:
    text = "<TABLE border='1'>inner</TABLE>"
    assert ascii_shape._TABLE_TAG_RE.findall(text) == []
    assert RE_TABLE_SPAN.search(text) is not None


def test_flip_case_spaced_close_tag() -> None:
    text = "<TABLE>inner</TABLE >"
    assert ascii_shape._TABLE_TAG_RE.findall(text) == []
    assert RE_TABLE_SPAN.search(text) is not None


def test_flip_case_span_findall_returns_whole_match() -> None:
    text = "<TABLE>inner</TABLE>"
    assert RE_TABLE_SPAN.findall(text) == ["<TABLE>inner</TABLE>"]
