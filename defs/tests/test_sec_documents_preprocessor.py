"""Unit tests for defs.sec_documents preprocessor and representation models."""

from __future__ import annotations

from defs.sec_documents import (
    DocumentPreprocessor,
    DocumentRepresentation,
    strip_envelope_text,
    strip_sgml_document_wrapper,
)


def test_decode_bytes_encodings() -> None:
    pre = DocumentPreprocessor()

    # UTF-8
    utf8_bytes = "Hello World — ©".encode()
    text, enc = pre.decode_bytes(utf8_bytes)
    assert enc == "utf-8"
    assert "©" in text

    # Windows-1252 (smart quote 0x93/0x94 invalid in UTF-8)
    cp1252_bytes = b"\x93Smart Quotes\x94"
    text, enc = pre.decode_bytes(cp1252_bytes)
    assert enc == "cp1252"
    assert "Smart Quotes" in text

    # Empty
    text, enc = pre.decode_bytes(b"")
    assert text == ""
    assert enc == "utf-8"


def test_strip_sgml_document_wrapper() -> None:
    raw = "<DOCUMENT>\n<TYPE>10-K\n<TEXT>\nItem 1. Business\n</TEXT>\n</DOCUMENT>"
    stripped = strip_sgml_document_wrapper(raw)
    assert stripped == "Item 1. Business"

    no_wrapper = "<html><body>Standard HTML</body></html>"
    assert strip_sgml_document_wrapper(no_wrapper) == no_wrapper


def test_strip_envelope_text() -> None:
    raw = (
        "-----BEGIN PRIVACY-ENHANCED MESSAGE-----\n"
        "Header: Info\n\n"
        "<DOCUMENT>\n<TYPE>10-K\n<TEXT>\nPayload Inside\n</TEXT>\n</DOCUMENT>\n"
        "-----END PRIVACY-ENHANCED MESSAGE-----"
    )
    stripped = strip_envelope_text(raw)
    assert stripped == "Payload Inside"


def test_preprocessor_ascii_pre() -> None:
    pre = DocumentPreprocessor()
    html_pre = (
        "<html><body><pre>   Fixed Width Form 10-K Content   </pre></body></html>"
    )
    result = pre.preprocess(html_pre.encode("utf-8"))
    assert result.representation == "ascii"
    assert result.metadata.get("ascii_pre_wrapper") is True
    assert "Fixed Width Form 10-K Content" in result.cleaned_text
    assert "<pre>" not in result.cleaned_text.lower()


def test_preprocessor_html() -> None:
    pre = DocumentPreprocessor()
    html_content = (
        "<html><head><style>.cls{color:red;}</style></head>"
        "<body><div>Item 1. Business</div></body></html>"
    )
    result = pre.preprocess(html_content.encode("utf-8"))
    assert result.representation == "html"
    assert result.has_html_tags is True
    assert "Item 1. Business" in result.cleaned_text
    assert ".cls" not in result.cleaned_text


def test_preprocessor_plain_ascii() -> None:
    pre = DocumentPreprocessor()
    text = "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\nWashington, D.C."
    result = pre.preprocess(text.encode("utf-8"))
    assert result.representation == "ascii"
    assert result.has_html_tags is False
    assert result.word_count == 8
    assert "SECURITIES" in result.cleaned_text


def test_document_representation_properties() -> None:
    assert DocumentRepresentation.HTML.is_html is True
    assert DocumentRepresentation.HTML.is_ascii is False
    assert DocumentRepresentation.ASCII_PLAIN.is_ascii is True
    assert DocumentRepresentation.ASCII_PRE.is_ascii is True
    assert DocumentRepresentation.XML.is_xml is True
