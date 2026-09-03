"""Tests for Stage 3 DeepNormalizer."""

from __future__ import annotations

import importlib

forms_base = importlib.import_module("phases.025_webpage_storage.processors.forms.base")
normalizer_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.normalizer"
)

PreprocessedDocument = forms_base.PreprocessedDocument
DeepNormalizer = normalizer_mod.DeepNormalizer
GenericPreprocessor = importlib.import_module(
    "phases.025_webpage_storage.processors.preprocessor"
).GenericPreprocessor


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
    assert "Metric" in normalized
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


def test_deep_normalizer_cover_metadata_conversion() -> None:
    normalizer = DeepNormalizer()
    html = """
    <html>
    <body>
    <p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
    <p>FORM 10-K</p>
    <table>
      <tr><td>Delaware</td><td></td><td>13-2624428</td></tr>
      <tr><td>(State of Incorporation)</td><td></td><td>(I.R.S. Employer Identification No.)</td></tr>
      <tr><td>270 Park Avenue, New York, New York</td><td></td><td>10017</td></tr>
      <tr><td>(Address of principal executive offices)</td><td></td><td>(Zip Code)</td></tr>
    </table>
    <p>ITEM 1. BUSINESS</p>
    <table border="1">
      <tr><th>Year</th><th>Revenue</th><th>Net Income</th></tr>
      <tr><td>2024</td><td>$100,000</td><td>$10,000</td></tr>
      <tr><td>2025</td><td>$120,000</td><td>$15,000</td></tr>
    </table>
    </body>
    </html>
    """
    prep = PreprocessedDocument(
        raw_text=html,
        cleaned_text=html,
        word_count=50,
        has_html_tags=True,
        detected_encoding="utf-8",
        metadata={"form": "10-K"},
    )
    normalized = normalizer.normalize(prep)

    # 1. Cover layout is preserved as canonical normalized source text.
    assert "Delaware" in normalized
    assert "(State of Incorporation)" in normalized
    assert "13-2624428" in normalized
    assert "(I.R.S. Employer Identification No.)" in normalized
    assert "270 Park Avenue, New York, New York" in normalized
    assert "(Address of principal executive offices)" in normalized
    assert "10017" in normalized
    assert "(Zip Code)" in normalized

    # 2. Subsequent financial table converted to structured ASCII table
    assert "ITEM 1. BUSINESS" in normalized
    assert "Year" in normalized
    assert "$100,000" in normalized
    assert "Revenue" in normalized
    assert "$100,000" in normalized


def test_deep_normalizer_body_start_consumes_toc_end() -> None:
    """Body-start analysis receives a real TOC_END, not None."""
    normalizer = DeepNormalizer()
    text = (
        "UNITED STATES\n"
        "SECURITIES AND EXCHANGE COMMISSION\n"
        "WASHINGTON, D.C. 20549\n"
        "FORM 10-K\n"
        "ACME CORPORATION\n"
        "(Exact name of registrant as specified in its charter)\n"
        "\n"
        "TABLE OF CONTENTS\n"
        "ITEM 1. BUSINESS .......................... 1\n"
        "ITEM 1A. RISK FACTORS ..................... 8\n"
        "\n"
        "PART I\n"
        "\n"
        "ITEM 1. BUSINESS\n"
        "\n"
        "The Company was founded in 1985 and operates manufacturing facilities "
        "worldwide. It provides products to customers through its market "
        "segments.\n"
    )
    prep = PreprocessedDocument(
        raw_text=text,
        cleaned_text=text,
        word_count=80,
        has_html_tags=False,
        detected_encoding="utf-8",
        metadata={"form": "10-K"},
    )
    result = normalizer.normalize_result(prep)
    assert result.body_start is not None
    lines = result.text.splitlines()
    assert lines[result.body_start.line].strip() == "PART I"
    assert result.body_start.first_unit_line >= result.body_start.line


def test_deep_normalizer_removes_validated_html_markers_without_ascii_reflow() -> None:
    html = """<html><body>
    <div class="page-number">1</div>
    <p>First page paragraph.</p>
    <div class="page-number">2</div>
    <p>Second page paragraph.</p>
    <div class="page-number">3</div>
    <p>Third page paragraph.</p>
    </body></html>"""
    preprocessed = GenericPreprocessor().preprocess(html.encode("utf-8"))

    assert preprocessed.representation == "html"
    result = DeepNormalizer().normalize_result(preprocessed)

    assert "page-number" not in result.text
    assert "First page paragraph." in result.text
    assert "Third page paragraph." in result.text
    assert result.reflow is None
    assert result.page_analysis is not None
    assert result.page_analysis.coordinate_frame == "html"
