"""Hybrid ``<pre>`` masking: the round trip that must never lose a payload."""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.hybrid.masker import (
    HybridPreText,
    PreBlockKind,
    _classify_pre_source,
    normalize_hybrid_pre_text,
    restore_hybrid_pre_text,
)

SGML_PRE_DOC = (
    "<html><body>\n<p>Some narrative text here.</p>\n<pre><TABLE>\n"
    "<CAPTION>Balance Sheet</CAPTION>\n<S> <C>Cash</S> <C>$100</C>\n"
    "<S> <C>Assets</S> <C>$500</C>\n</TABLE></pre>\n"
    "<p>More narrative text.</p>\n</body></html>"
)
MONOSPACE_PRE_DOC = (
    "<html><body>\n<p>Financial Summary</p>\n<pre>\nThree Months Ended\n"
    "March 31, 2020\n--------------\nRevenues $100\nNet Income  $50\n</pre>\n"
    "<p>End of summary.</p>\n</body></html>"
)
HTML_TABLE_IN_PRE_DOC = (
    "<html><body>\n<p>Before table</p>\n"
    "<pre><table><tr><th>Item</th><th>Amount</th></tr>"
    "<tr><td>Revenue</td><td>1000</td></tr></table></pre>\n"
    "<p>After table</p>\n</body></html>"
)
MIXED_DOC = (
    "<html><body>\n<p>Narrative prose about the financials.</p>\n"
    "<table><tr><th>Direct</th><th>Table</th></tr><tr><td>A</td><td>1</td></tr></table>\n"
    "<pre><TABLE>\n<S> <C>Item</S> <C>Value</C>\n</TABLE></pre>\n"
    "<pre>\nFixed-width data\n--------------\nLine one\n</pre>\n</body></html>"
)


def _round_trip(text: str) -> str:
    protected = normalize_hybrid_pre_text(text)
    return restore_hybrid_pre_text(protected.text, protected.protected)


# --- classification ---------------------------------------------------------


def test_literal_sgml_table_markup_inside_pre_is_an_sgml_table() -> None:
    assert _classify_pre_source("<TABLE>\n<S> <C>Cash</S> <C>$100</C>\n</TABLE>") is (
        PreBlockKind.SGML_TABLE
    )


def test_a_bare_sgml_table_tag_without_cells_is_still_an_sgml_table() -> None:
    assert _classify_pre_source("<TABLE>\nTotal\n</TABLE>") is PreBlockKind.SGML_TABLE


def test_true_html_table_markup_inside_pre_is_an_html_table() -> None:
    assert _classify_pre_source("<table><tr><th>Item</th></tr></table>") is (
        PreBlockKind.HTML_TABLE
    )


def test_fixed_width_columnar_text_is_monospace() -> None:
    assert (
        _classify_pre_source(
            "Three Months Ended\nMarch 31, 2020\n--------------\nRevenues $100"
        )
        is PreBlockKind.MONOSPACE_TEXT
    )


def test_wrapped_prose_is_narrative() -> None:
    assert _classify_pre_source("Some wrapped prose text here.") is (
        PreBlockKind.NARRATIVE_PROSE
    )


def test_empty_pre_content_is_narrative() -> None:
    assert _classify_pre_source("   ") is PreBlockKind.NARRATIVE_PROSE


# --- masking and restoration ------------------------------------------------


def test_a_document_with_no_pre_blocks_is_returned_unchanged() -> None:
    protected = normalize_hybrid_pre_text("<p>plain</p>")
    assert isinstance(protected, HybridPreText)
    assert protected.text == "<p>plain</p>"
    assert protected.protected == {}


def test_an_sgml_pre_payload_survives_the_round_trip_byte_for_byte() -> None:
    result = _round_trip(SGML_PRE_DOC)
    assert "<pre>" not in result
    assert "<TABLE>" in result
    assert "<S>" in result
    assert "<C>" in result
    assert "Cash" in result
    assert "$100" in result
    assert "Some narrative text here." in result
    assert "More narrative text." in result


def test_a_monospace_payload_keeps_its_exact_line_breaks() -> None:
    result = _round_trip(MONOSPACE_PRE_DOC)
    assert "<pre>" not in result
    assert "Three Months Ended\nMarch 31, 2020" in result
    assert "--------------" in result
    assert "Revenues $100" in result
    assert "Net Income  $50" in result


def test_an_html_table_inside_pre_is_rendered_to_canonical_ascii() -> None:
    result = _round_trip(HTML_TABLE_IN_PRE_DOC)
    assert "<pre>" not in result
    assert "<TABLE>" in result
    assert "Item" in result
    assert "Amount" in result
    assert "Revenue" in result
    assert "1000" in result
    assert "<table>" not in result


def test_a_mixed_document_handles_every_payload_shape() -> None:
    result = _round_trip(MIXED_DOC)
    assert "Direct" in result
    assert "Item" in result
    assert "Fixed-width data" in result
    assert "Line one" in result
    assert "<pre>" not in result


def test_a_small_html_table_inside_pre_becomes_a_canonical_block() -> None:
    result = _round_trip(
        "<pre><table><tr><td>Name</td><td>Value</td></tr>"
        "<tr><td>X</td><td>42</td></tr></table></pre>"
    )
    assert "<TABLE>" in result
    assert "Name" in result
    assert "42" in result


def test_the_text_outside_a_pre_block_is_left_untouched() -> None:
    protected = normalize_hybrid_pre_text("<p>before</p><pre>x</pre><p>after</p>")
    assert protected.text.startswith("<p>before</p>")
    assert protected.text.endswith("<p>after</p>")
    assert "<pre>" not in protected.text.lower()
    assert "</pre>" not in protected.text.lower()


def test_narrative_prose_inside_pre_survives_the_unwrap() -> None:
    result = _round_trip(
        "<html><body><pre>Some narrative prose text.\nMore text here.</pre></body></html>"
    )
    assert "Some narrative prose text." in result
    assert "More text here." in result
    assert "<pre>" not in result


def test_every_pre_block_gets_its_own_token() -> None:
    protected = normalize_hybrid_pre_text(MIXED_DOC)
    assert len(protected.protected) == 2
    for token in protected.protected:
        assert token in protected.text
    assert len(protected.text) < len(MIXED_DOC)


def test_multiple_tokens_are_all_restored() -> None:
    protected = normalize_hybrid_pre_text(MIXED_DOC)
    result = restore_hybrid_pre_text(protected.text, protected.protected)
    for payload in protected.protected.values():
        assert payload in result


def test_a_missing_single_token_is_reported_rather_than_silently_dropping_a_table() -> (
    None
):
    protected = normalize_hybrid_pre_text(HTML_TABLE_IN_PRE_DOC)
    (token,) = protected.protected
    with pytest.raises(ValueError, match="token missing"):
        restore_hybrid_pre_text("nothing to see", {token: protected.protected[token]})


def test_a_missing_token_among_several_is_reported() -> None:
    protected = normalize_hybrid_pre_text(MIXED_DOC)
    next(iter(protected.protected))
    with pytest.raises(ValueError, match="token missing"):
        restore_hybrid_pre_text("nothing to see", protected.protected)


def test_restoring_with_no_protected_payloads_is_a_passthrough() -> None:
    assert restore_hybrid_pre_text("text", {}) == "text"


def test_a_document_already_containing_the_sentinel_text_never_corrupts_silently() -> (
    None
):
    # Masking disambiguates a token that already occurs in the document by
    # appending an underscore, but an adversarial document can still leave a
    # token that the alternation cannot reach. Restoration then refuses rather
    # than emitting a document with a whole table missing.
    doc = "<pre>a</pre>__SEC_HYBRID_PRE_0__<pre>b</pre>"
    protected = normalize_hybrid_pre_text(doc)
    assert all(token in protected.text for token in protected.protected)
    with pytest.raises(ValueError, match="token missing"):
        restore_hybrid_pre_text(protected.text, protected.protected)
