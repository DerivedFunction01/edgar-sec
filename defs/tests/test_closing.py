"""Contract tests for conservative closing-region detection."""

from __future__ import annotations

from defs.sec_forms.cover.closing import find_closing_span

BODY = (
    "PART I\n"
    "ITEM 1. BUSINESS\n"
    "\n"
    "We are an enterprise software company.\n"
    "Our customers include major healthcare providers."
)


def test_bare_signatures_heading_is_detected() -> None:
    text = BODY + "\n\nSIGNATURES\n\nPursuant to the requirements of Section 13."
    result = find_closing_span(text, search_from=1)
    assert result is not None
    assert result.kind == "signatures"
    assert result.start_line == len(BODY.splitlines()) + 1
    assert result.confidence >= 0.85
    assert result.evidence[0].name == "signatures_heading"


def test_signatures_heading_with_pursuant_suffix() -> None:
    text = (
        BODY
        + "\n\nSIGNATURES\nPursuant to the requirements of the Securities Exchange\n"
        "Act of 1934, this report has been signed below by the following persons\n"
        "on behalf of the Registrant.\n"
        "\nDate: March 1, 2024\nBy: /s/ Jane Doe\n"
    )
    result = find_closing_span(text, search_from=1)
    assert result is not None
    assert result.kind == "signatures"
    assert result.start_line == len(BODY.splitlines()) + 1


def test_slash_s_cluster_without_heading() -> None:
    text = BODY + "\n\nBy: /s/ John Smith\nTitle: Chief Executive Officer"
    result = find_closing_span(text, search_from=1)
    assert result is not None
    assert result.kind == "signatures"
    assert result.confidence >= 0.8
    assert result.evidence[0].name == "slash_s_signature"


def test_exhibit_index_heading() -> None:
    text = BODY + "\n\nEXHIBIT INDEX\n\n3.1 Articles of Incorporation"
    result = find_closing_span(text, search_from=1)
    assert result is not None
    assert result.kind == "exhibit_index"
    assert result.confidence >= 0.6


def test_signature_word_in_prose_is_not_closing() -> None:
    text = BODY + "\n\nThe signatures on the agreement were verified carefully."
    result = find_closing_span(text, search_from=1)
    assert result is None


def test_lowercased_signature_heading_is_not_closing() -> None:
    text = BODY + "\n\nsignatures of authorized officers follow"
    assert find_closing_span(text, search_from=1) is None


def test_toc_row_is_never_a_closing_signal() -> None:
    toc_rows = (
        "Item 1. Business ................. 1\n"
        "Item 1A. Risk Factors ............ 5\n"
        "SIGNATURES ....................... 60\n"
        "\nPART I\nITEM 1. BUSINESS\n" + BODY
    )
    text = toc_rows + "\n\n/s/ Jane Doe\n"
    result = find_closing_span(text, search_from=1)
    assert result is not None
    # The dotted SIGNATURES TOC row is rejected; the /s/ line is the signal.
    assert result.evidence[0].name == "slash_s_signature"


def test_search_from_bounds_the_scan() -> None:
    text = BODY + "\n\n/s/ Jane Doe\n"
    body_last = len(BODY.splitlines()) + 3
    assert find_closing_span(text, search_from=body_last) is None


def test_search_window_is_bounded() -> None:
    text = BODY + "\n" + "\n" * 1600 + "/s/ Jane Doe\n"
    assert find_closing_span(text, search_from=1) is None


def test_empty_and_short_documents_return_none() -> None:
    assert find_closing_span("") is None
    assert find_closing_span("\n\n") is None


def test_no_signal_in_plain_body() -> None:
    assert find_closing_span(BODY, search_from=1) is None
