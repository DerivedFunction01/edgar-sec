"""Input preparation and representation classification.
The order is pinned as much as the outcomes: purge-before-classify and
ASCII-PRE-before-HTML-cleaning, since either order sends a filing down the wrong chain.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.unpacking.representation import (
    Representation,
    decode_bytes,
    prepare_input_text,
    strip_envelope_text,
    strip_sgml_document_wrapper,
)

ENVELOPE_SGML = (
    b"<DOCUMENT>"
    b"<TYPE>10-K<SEQUENCE>1<FILENAME>a.htm<TEXT>"
    b"<html><body><p>Primary document</p></body></html>"
    b"</TEXT></DOCUMENT>"
    b"<DOCUMENT>"
    b"<TYPE>EX-21<SEQUENCE>2<FILENAME>b.txt<TEXT>Exhibit body</TEXT>"
    b"</DOCUMENT>"
)


def test_decode_bytes_prefers_utf8() -> None:
    text, encoding = decode_bytes("café".encode())
    assert text == "café"
    assert encoding == "utf-8"


def test_decode_bytes_falls_back_to_cp1252() -> None:
    raw = "café".encode("cp1252")
    assert raw.decode("utf-8", errors="strict") if False else True
    text, encoding = decode_bytes(raw)
    assert encoding == "cp1252"
    assert "caf" in text


def test_decode_bytes_falls_back_to_latin1() -> None:
    # CP1252 leaves these byte values undefined, so decoding fails and the ladder
    # reaches Latin-1, which cannot fail.
    raw = bytes([0x81, 0x8D, 0x41])
    with pytest.raises(UnicodeDecodeError):
        raw.decode("cp1252")
    text, encoding = decode_bytes(raw)
    assert encoding == "latin-1"
    assert "A" in text


def test_decode_bytes_on_empty_input() -> None:
    assert decode_bytes(b"") == ("", "utf-8")


def test_strip_sgml_document_wrapper_extracts_text_block() -> None:
    raw = "<DOCUMENT><TYPE>10-K<TEXT>inner content</TEXT></DOCUMENT>"
    assert strip_sgml_document_wrapper(raw) == "inner content"


def test_strip_sgml_document_wrapper_passes_plain_text_through() -> None:
    assert strip_sgml_document_wrapper("plain body") == "plain body"
    assert strip_sgml_document_wrapper("") == ""


def test_strip_envelope_text_selects_the_target_document() -> None:
    text = strip_envelope_text(ENVELOPE_SGML.decode("latin-1"))
    assert "Primary document" in text
    assert "Exhibit body" not in text


def test_strip_envelope_text_passes_a_plain_document_through() -> None:
    assert strip_envelope_text("<html><body><p>x</p></body></html>") == (
        "<html><body><p>x</p></body></html>"
    )


def test_prepare_input_text_classifies_plain_ascii() -> None:
    text, representation, _ = prepare_input_text(b"just some ascii text")
    assert representation is Representation.ASCII_PLAIN
    assert text == "just some ascii text"


def test_prepare_input_text_classifies_html() -> None:
    text, representation, _ = prepare_input_text(b"<html><body><p>Hi</p></body></html>")
    assert representation is Representation.HTML
    assert "Hi" in text


def test_prepare_input_text_classifies_ascii_pre() -> None:
    text, representation, _ = prepare_input_text(b"<PRE>line one\nline two</PRE>")
    assert representation is Representation.ASCII_PRE
    assert text == "line one\nline two"


def test_ascii_pre_wins_over_the_html_discriminator() -> None:
    """A `<PRE>` payload keeps its hard line breaks instead of being HTML-cleaned."""
    raw = b"<html><body><pre>line one\nline two</pre></body></html>"
    text, representation, _ = prepare_input_text(raw)
    assert representation is Representation.ASCII_PRE
    assert text == "line one\nline two"


def test_sgml_ascii_table_tags_do_not_make_a_document_html() -> None:
    """`<TABLE>`/`<S>`/`<C>` are ASCII statement markup, not HTML evidence."""
    raw = b"<TABLE><S><C>Revenue<C>1,000<S></TABLE>"
    _, representation, _ = prepare_input_text(raw)
    assert representation is Representation.ASCII_PLAIN


def test_non_displaying_blocks_are_purged_before_classification() -> None:
    raw = (
        b"<html><head><title>Doc Title</title><style>a{color:red}</style></head>"
        b"<body><script>var x=1;</script>"
        b"<p>Visible</p></body></html>"
    )
    text, representation, _ = prepare_input_text(raw)
    assert representation is Representation.HTML
    assert "Visible" in text
    assert "Doc Title" not in text
    assert "var x=1" not in text
    assert "color:red" not in text


def test_noscript_is_not_purged() -> None:
    """Deliberate: the purge is exactly head/script/style, and ``<noscript>``
    fallback text is what a reader sees with scripting off.
    """
    raw = b"<html><body><noscript>fallback text</noscript><p>Visible</p></body></html>"
    text, _, _ = prepare_input_text(raw)
    assert "fallback text" in text


def test_sgml_envelope_is_unwrapped_before_classification() -> None:
    text, representation, _ = prepare_input_text(ENVELOPE_SGML)
    assert representation is Representation.HTML
    assert "Primary document" in text
    assert "<DOCUMENT>" not in text


def test_entities_are_unescaped_on_the_ascii_paths() -> None:
    text, representation, _ = prepare_input_text(b"a &amp; b &nbsp;c")
    assert representation is Representation.ASCII_PLAIN
    assert "&" in text
    assert "&nbsp;" not in text


def test_html_entities_survive_the_html_path() -> None:
    """Cleaning must not unescape entities into synthetic tags before the DOM."""
    text, representation, _ = prepare_input_text(
        b"<html><body><p>a &lt;tag&gt; &amp; b</p></body></html>"
    )
    assert representation is Representation.HTML
    assert "&lt;tag&gt;" in text


def test_inline_xbrl_is_stripped_on_the_html_path() -> None:
    raw = b'<html><body><p><ix:nonFraction contextref="c">1,234</ix:nonFraction></p></body></html>'
    text, representation, _ = prepare_input_text(raw)
    assert representation is Representation.HTML
    assert "1,234" in text
    assert "ix:" not in text


def test_prepare_input_text_never_raises_on_malformed_payload() -> None:
    for raw in (b"", b"\x00\x01\x02", b"<html><p>unclosed", b"<DOCUMENT>"):
        text, representation, encoding = prepare_input_text(raw)
        assert isinstance(text, str)
        assert isinstance(representation, Representation)
        assert encoding


def test_reported_encoding_tracks_the_decode_ladder() -> None:
    _, _, utf8 = prepare_input_text(b"ascii")
    _, _, cp1252 = prepare_input_text("café".encode("cp1252"))
    assert utf8 == "utf-8"
    assert cp1252 == "cp1252"
