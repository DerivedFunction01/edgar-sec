"""Tests for Stage 3 DeepNormalizer."""

from __future__ import annotations

import importlib

forms_base = importlib.import_module("phases.025_webpage_storage.processors.forms.base")
normalizer_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.normalizer"
)

PreprocessedDocument = forms_base.PreprocessedDocument
DeepNormalizer = normalizer_mod.DeepNormalizer


def test_deep_normalizer_table_conversion() -> None:
    normalizer = DeepNormalizer()

    html = """
    <html>
    <body>
    <p>ITEM 1. BUSINESS</p>
    <p>We manufacture widgets.</p>
    <table border="1">
      <tr><th>Year</th><th>Revenue</th><th>Net Income</th></tr>
      <tr><td>2001</td><td>$100,000</td><td>$10,000</td></tr>
      <tr><td>2002</td><td>$120,000</td><td>$15,000</td></tr>
    </table>
    <PAGE>
    <p>Page 2 of 10</p>
    <p>ITEM 7. MD&A</p>
    <p>Operations increased substantially.</p>
    </body>
    </html>
    """

    prep = PreprocessedDocument(
        raw_text=html,
        cleaned_text=html,
        word_count=50,
        has_html_tags=True,
        detected_encoding="utf-8",
    )

    normalized = normalizer.normalize(prep)

    # 1. Header standardized
    assert "ITEM 1. BUSINESS" in normalized
    assert "ITEM 7. MD&A" in normalized

    # 2. Page markers stripped
    assert "<PAGE>" not in normalized
    assert "Page 2 of 10" not in normalized

    # 3. HTML table converted into structured ASCII grid
    assert "Revenue" in normalized
    assert "100,000" in normalized
    assert "<tr>" not in normalized.lower()
    assert "<td>" not in normalized.lower()


def test_deep_normalizer_spacer_trimming() -> None:
    normalizer = DeepNormalizer()

    # Table with blank spacer column (col 1) and empty spacer row
    html = """
    <table>
      <tr><th>Metric</th><th></th><th>2003</th></tr>
      <tr><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>
      <tr><td>Sales</td><td></td><td>$5,000</td></tr>
    </table>
    """
    prep = PreprocessedDocument(
        raw_text=html,
        cleaned_text=html,
        word_count=10,
        has_html_tags=True,
        detected_encoding="utf-8",
    )
    normalized = normalizer.normalize(prep)
    assert "<TABLE>" in normalized
    assert "Sales" in normalized
    assert "$5,000" in normalized


def test_deep_normalizer_xml_stripping() -> None:
    normalizer = DeepNormalizer()
    text = "Total assets were <ix:nonFraction unitRef='usd' decimals='0'>1500000</ix:nonFraction> dollars."
    prep = PreprocessedDocument(
        raw_text=text,
        cleaned_text=text,
        word_count=10,
        has_html_tags=False,
        detected_encoding="utf-8",
    )
    normalized = normalizer.normalize(prep)
    assert "<ix:" not in normalized
    assert "1500000" in normalized
