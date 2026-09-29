"""Tests for conservative closing-region detection."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.closing import find_closing_span

DOC = """\
PART II

ITEM 5. Other Information

The Company disclosed the matters described above.

SIGNATURES

Pursuant to the requirements of Section 13 of the Exchange Act, the registrant \
has duly authorized this report.

/s/ Jane Q. Registrant
Jane Q. Registrant
Chief Executive Officer"""


def test_finds_signature_heading() -> None:
    span = find_closing_span(DOC)
    assert span is not None
    assert span.kind == "signatures"
    assert span.start_line == DOC.splitlines().index("SIGNATURES")
    assert span.confidence == 0.9


def test_finds_slash_s_signature() -> None:
    text = "body prose here\n/s/ Jane Q. Registrant"
    span = find_closing_span(text)
    assert span is not None
    assert span.kind == "signatures"
    assert span.start_line == 1
    assert span.confidence == 0.85


def test_finds_exhibit_index() -> None:
    text = "body prose here\nEXHIBIT INDEX\n\n10.1 Agreement"
    span = find_closing_span(text)
    assert span is not None
    assert span.kind == "exhibit_index"
    assert span.confidence == 0.7


def test_search_from_skips_earlier_matches() -> None:
    text = "SIGNATURES\ncover signature label\nbody\nSIGNATURES"
    span = find_closing_span(text, search_from=2)
    assert span is not None
    assert span.start_line == 3


def test_toc_signature_row_is_not_a_closing_signal() -> None:
    text = "ITEM 1. Business .... 1\nSIGNATURES ..... 60"
    assert find_closing_span(text) is None


def test_lowercase_signatures_is_not_exact() -> None:
    text = "body\nsignatures of auditors"
    assert find_closing_span(text) is None


def test_no_signal_returns_none() -> None:
    assert find_closing_span("just some body prose") is None
    assert find_closing_span("") is None


def test_evidence_records_the_signal() -> None:
    span = find_closing_span(DOC)
    assert span is not None
    assert span.evidence
    assert span.evidence[0].name == "signatures_heading"
    assert span.approximate is True
