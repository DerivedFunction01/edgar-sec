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
