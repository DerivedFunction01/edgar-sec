"""Tests for Stage 1 GenericPreprocessor."""

from __future__ import annotations

import importlib

preprocessor_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.preprocessor"
)
GenericPreprocessor = preprocessor_mod.GenericPreprocessor


def test_decode_bytes_encodings() -> None:
    preprocessor = GenericPreprocessor()

    # 1. UTF-8
    u_bytes = "Form 10-K \u2014 Annual Report".encode("utf-8")
    text, enc = preprocessor.decode_bytes(u_bytes)
    assert enc == "utf-8"
    assert "Annual Report" in text

    # 2. Latin-1 / CP1252
    l_bytes = "Kellwood Co \xa9 2002".encode("latin-1")
    text, enc = preprocessor.decode_bytes(l_bytes)
    assert "Kellwood Co" in text

    # 3. Empty
    text, enc = preprocessor.decode_bytes(b"")
    assert text == ""
    assert enc == "utf-8"


def test_preprocess_strips_envelope_and_unescapes() -> None:
    preprocessor = GenericPreprocessor()
    raw = b"""<DOCUMENT>
<TYPE>10-K
<SEQUENCE>1
<FILENAME>form10k.htm
<TEXT>
<HTML>
<HEAD><TITLE>Report</TITLE><STYLE>.bold { font-weight: bold; }</STYLE></HEAD>
<BODY>
<P>Item 1.&nbsp;Business &amp; Operations</P>
</BODY>
</HTML>
</TEXT>
</DOCUMENT>"""

    doc = preprocessor.preprocess(raw)
    assert doc.word_count >= 3
    assert doc.has_html_tags is True
    assert "Business & Operations" in doc.cleaned_text
    assert "<STYLE>" not in doc.cleaned_text
    assert "<HEAD>" not in doc.cleaned_text


def test_preprocess_ascii_sec_table_not_flagged_as_html() -> None:
    preprocessor = GenericPreprocessor()
    raw_ascii = b"""<DOCUMENT>
<TYPE>10-K
<TEXT>
ITEM 1. BUSINESS
Southern Company operations.

<TABLE>
<CAPTION>
Operating Results
<S>                       <C>           <C>
Total Net Income          $  1,250,000  $  1,100,000
</TABLE>
</TEXT>
</DOCUMENT>"""

    doc = preprocessor.preprocess(raw_ascii)
    assert doc.has_html_tags is False
    assert "Operating Results" in doc.cleaned_text
    assert "Total Net Income" in doc.cleaned_text


def test_preprocess_html_body_pre_wrapper_routes_inner_payload_to_ascii() -> None:
    raw = b"""<DOCUMENT>
<TYPE>10-K
<TEXT>
<HTML><HEAD><STYLE>pre { font: monospace; }</STYLE></HEAD><BODY>
<PRE>
<PAGE>
ITEM 1. BUSINESS
The company operates a business.
</PRE>
</BODY></HTML>
</TEXT>
</DOCUMENT>"""
    doc = GenericPreprocessor().preprocess(raw)
    assert doc.has_html_tags is False
    assert doc.representation == "ascii"
    assert doc.metadata["ascii_pre_wrapper"] is True
    assert doc.cleaned_text.lstrip().startswith("<PAGE>")
    assert "<HTML>" not in doc.cleaned_text


def test_preprocess_pre_payload_with_visible_layout_markup_stays_html() -> None:
    raw = b"<HTML><BODY><PRE><div class='content'>Report</div></PRE></BODY></HTML>"
    doc = GenericPreprocessor().preprocess(raw)
    assert doc.has_html_tags is True
    assert doc.metadata.get("ascii_pre_wrapper") is not True
