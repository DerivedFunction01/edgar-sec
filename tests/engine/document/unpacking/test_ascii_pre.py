"""ASCII-PRE discrimination.
The question is never "does this contain `<PRE>`" but "is `<PRE>` the *only*
thing between the payload and the text".
"""

from __future__ import annotations

from edgar_sec.engine.document.unpacking.ascii_pre import extract_ascii_pre


def test_bare_pre_is_a_transport_wrapper() -> None:
    assert extract_ascii_pre("<pre>plain ascii</pre>") == "plain ascii"


def test_pre_inside_an_html_envelope_is_still_a_wrapper() -> None:
    html = "<html><body><pre>ascii body</pre></body></html>"
    assert extract_ascii_pre(html) == "ascii body"


def test_visible_text_outside_pre_disqualifies_the_wrapper() -> None:
    """Tags outside the `<PRE>` are fine; visible characters are not."""
    assert extract_ascii_pre(
        "<html><head><title>x</title></head><pre>a</pre></html>"
    ) is (None)
    assert (
        extract_ascii_pre("<html><body><pre>a</pre><p>text</p></body></html>") is None
    )


def test_payload_keeps_its_internal_line_breaks() -> None:
    assert extract_ascii_pre("<pre>line one\nline two\n</pre>") == (
        "line one\nline two\n"
    )


def test_uppercase_pre_tag_is_recognized() -> None:
    assert extract_ascii_pre("<PRE>upper</PRE>") == "upper"


def test_pre_with_attributes_is_recognized() -> None:
    assert extract_ascii_pre('<pre class="x" cols="80">body</pre>') == "body"


def test_two_pre_blocks_are_not_a_wrapper() -> None:
    assert extract_ascii_pre("<pre>one</pre><pre>two</pre>") is None


def test_no_pre_block_returns_none() -> None:
    assert extract_ascii_pre("<html><body><p>real html</p></body></html>") is None


def test_prose_outside_pre_disqualifies_the_wrapper() -> None:
    assert extract_ascii_pre("leading prose<pre>ascii</pre>") is None
    assert extract_ascii_pre("<pre>ascii</pre>trailing prose") is None


def test_markup_inside_pre_disqualifies_the_wrapper() -> None:
    """A `<PRE>` holding real tags is rendered HTML, not transported ASCII."""
    assert extract_ascii_pre("<pre><table><tr><td>x</td></tr></table></pre>") is None
    assert extract_ascii_pre("<pre><p>paragraph</p></pre>") is None
    assert extract_ascii_pre("<pre><br>line</pre>") is None
    assert extract_ascii_pre("<pre><font face='Arial'>x</font></pre>") is None
    assert extract_ascii_pre("<pre><ul><li>item</li></ul></pre>") is None


def test_non_layout_markup_inside_pre_is_tolerated() -> None:
    """Only layout tags disqualify; an escaped bracket is just text."""
    assert extract_ascii_pre("<pre>a < b and c > d</pre>") == "a < b and c > d"


def test_empty_payload_returns_none() -> None:
    assert extract_ascii_pre("") is None
    assert extract_ascii_pre("   ") is None


def test_empty_pre_body_returns_empty_payload() -> None:
    assert extract_ascii_pre("<pre></pre>") == ""


def test_unterminated_pre_returns_none() -> None:
    assert extract_ascii_pre("<pre>never closed") is None
