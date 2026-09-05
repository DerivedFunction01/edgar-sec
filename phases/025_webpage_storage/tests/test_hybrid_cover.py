"""Unit and integration tests for HybridCoverPreprocessor."""

from __future__ import annotations

import importlib

shared_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.forms.shared.hybrid_cover"
)
base_mod = importlib.import_module("phases.025_webpage_storage.processors.forms.base")
normalizer_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.normalizer"
)
cover_mod = importlib.import_module("defs.sec_forms.cover")
HybridCoverPreprocessor = shared_mod.HybridCoverPreprocessor
PreprocessedDocument = base_mod.PreprocessedDocument
DeepNormalizer = normalizer_mod.DeepNormalizer
get_profile = cover_mod.get_profile

ANNUAL_COVER_PLUS_BODY = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
FORM 10-K
For the fiscal year ended December 31, 2024
Commission file number 001-13665
ACME CORPORATION
(Exact name of registrant as specified in its charter)
Delaware          12-3456789
(State or other jurisdiction of incorporation or organization)
Documents incorporated by reference: Portions of Part III.

PART I

Item 1. Business

The Company was incorporated in Delaware in 1985 and manufactures widgets for \
industrial customers throughout North America and Europe.\
"""


def test_hybrid_cover_preprocessor_address_and_state_table() -> None:
    html_doc = """
    <html>
      <body>
        <div>
          UNITED STATES<br>
          SECURITIES AND EXCHANGE COMMISSION<br>
          WASHINGTON, D.C. 20549<br>
          FORM 10-K<br>
          For the fiscal<br>
          year ended December 31, 2024<br>
          Commission file<br>
          number 001-13665<br>
          JARDEN CORPORATION<br>
          (Exact name of registrant as specified in its charter)<br>
          <table>
            <tr>
              <td>Delaware</td>
              <td>35-1828377</td>
            </tr>
            <tr>
              <td>(State or other jurisdiction of incorporation or organization)</td>
              <td>(I.R.S. Employer Identification No.)</td>
            </tr>
            <tr>
              <td>1800 North Military Trail, Boca Raton, FL</td>
              <td>33431</td>
            </tr>
            <tr>
              <td>(Address of principal executive offices)</td>
              <td>(Zip Code)</td>
            </tr>
          </table>
              <p>Registrant's telephone number, including area code: (561) 447-2520</p>
              <p>ITEM 1. BUSINESS</p>
            </div>
      </body>
    </html>
    """

    preprocessor = HybridCoverPreprocessor()
    result = preprocessor.preprocess(html_doc, company_name="Jarden Corporation")

    assert result.matched is True
    text = result.html

    # Check banner healed
    assert "UNITED STATES SECURITIES AND EXCHANGE COMMISSION" in text
    assert "For the fiscal year ended December 31, 2024" in text
    assert "Commission file number 001-13665" in text

    # Check state & EIN cleanly paired
    assert "Delaware" in text
    assert "(State or other jurisdiction of incorporation or organization)" in text
    assert "35-1828377" in text
    assert "(I.R.S. Employer" in text and "Identification No.)" in text

    # Check address & zip present
    assert "1800 North Military Trail, Boca Raton, FL" in text
    assert "33431" in text
    assert "(Address of principal executive offices)" in text
    assert "(Zip Code)" in text


def test_hybrid_cover_preprocessor_section_12b_table() -> None:
    html_doc = """
    <html>
      <body>
              <p>Securities registered pursuant to Section 12(b) of the Act:</p>
            <table>
              <tr>
                <th>Title of each class</th>
                <th>Trading Symbol(s)</th>
                <th>Name of each exchange on which registered</th>
              </tr>
              <tr>
                <td>Common Stock, $0.01 par value</td>
                <td>JAH</td>
                <td>New York Stock Exchange</td>
              </tr>
            </table>
            <p>ITEM 1. BUSINESS</p>
          </body>
    </html>
    """

    preprocessor = HybridCoverPreprocessor()
    result = preprocessor.preprocess(html_doc)
    assert result.matched is True
    text = result.html

    # The table remains a structured ASCII block after HTML stripping.
    assert "Title of each class" in text
    assert "Trading Symbol(s)" in text
    assert "New York Stock Exchange" in text


def test_incorporated_reference_table_ends_before_part_heading() -> None:
    html_doc = """
    <html>
      <body>
        <p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
        <p>FORM 10-K</p>
        <p>Commission file number 001-13665</p>
        <table>
          <tr><td>Documents incorporated by reference: Parts I, II, and III.</td></tr>
          <tr><td>Portions of the proxy statement are incorporated herein.</td></tr>
        </table>
        <p>PART I</p>
      </body>
    </html>
    """
    result = HybridCoverPreprocessor().preprocess(html_doc)
    assert result.cover_boundary.method.value == "structural"
    assert "incorporated by reference" in result.html
    assert result.html.index("PART I") > result.html.index("incorporated by reference")


def test_html_cover_without_tables_receives_boundary() -> None:
    html_doc = """
    <html>
      <body>
        <p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
        <p>FORM 10-K</p>
        <p>Commission file number 001-13665</p>
        <p>Registrant ACME CORPORATION</p>
        <p>Documents incorporated by reference: Portions of Part III.</p>
        <h2>PART I</h2>
        <h3>ITEM 1. BUSINESS</h3>
        <p>The company operates worldwide.</p>
      </body>
    </html>
    """
    result = DeepNormalizer().normalize_result(
        PreprocessedDocument(
            raw_text=html_doc,
            cleaned_text=html_doc,
            word_count=len(html_doc.split()),
            has_html_tags=True,
            detected_encoding="utf-8",
        ),
        metadata={"form": "10-K"},
    )
    assert result.cover_boundary.end_line is not None
    assert result.cover_boundary.start_line is not None


def test_hybrid_cover_preprocessor_checkbox_grid() -> None:
    html_doc = """
    <html>
      <body>
        <table>
          <tr>
            <td>Large accelerated filer</td>
            <td>&#9746;</td>
            <td>Accelerated filer</td>
            <td>&#9744;</td>
          </tr>
          <tr>
            <td>Non-accelerated filer</td>
            <td>&#9744;</td>
            <td>Smaller reporting company</td>
            <td>&#9744;</td>
          </tr>
        </table>
      </body>
    </html>
    """

    preprocessor = HybridCoverPreprocessor()
    result = preprocessor.preprocess(html_doc)
    assert result.matched is True
    text = result.html

    # Checkboxes normalized to [X] and [ ]
    assert "Large accelerated filer" in text and "[X]" in text
    assert "Accelerated filer" in text and "[ ]" in text
    assert "Non-accelerated filer" in text and "[ ]" in text
    assert "Smaller reporting company" in text and "[ ]" in text


def test_adversarial_html_part_continuation_not_boundary() -> None:
    html_doc = """
    <html>
      <body>
        <p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
        <p>FORM 10-K</p>
        <p>Commission file number 001-13665</p>
        <p>Documents incorporated by reference: see Part III hereof.</p>
        <p>PART I</p>
        <p>ITEM 1. BUSINESS</p>
      </body>
    </html>
    """
    result = HybridCoverPreprocessor().preprocess(html_doc)
    assert result.cover_boundary.end_line is not None
    lines = result.html.splitlines()
    assert lines[result.cover_boundary.end_line].strip().upper() == "PART I"


def test_positive_ascii_cover_boundary_basic() -> None:
    text = ANNUAL_COVER_PLUS_BODY
    result = HybridCoverPreprocessor().preprocess(text)
    assert result.cover_boundary.method is not None


def test_positive_quarterly_cover_boundary() -> None:
    html_doc = """
    <html>
      <body>
        <p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
        <p>FORM 10-Q</p>
        <p>Commission file number 123</p>
        <p>Registrant ACME</p>
        <p>PART I</p>
        <p>Item 1. Financial Statements</p>
        <p>The Company reports quarterly results.</p>
      </body>
    </html>
    """
    result = HybridCoverPreprocessor(get_profile("10-Q")).preprocess(html_doc)
    assert result.cover_boundary.end_line is not None


def test_positive_html_toc_boundary_detected() -> None:
    html_doc = """
    <html>
      <body>
        <p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
        <p>FORM 10-K</p>
        <p>Commission file number 001-13665</p>
        <p>TABLE OF CONTENTS</p>
        <p>PART I</p>
        <p>ITEM 1. BUSINESS</p>
      </body>
    </html>
    """
    result = HybridCoverPreprocessor().preprocess(html_doc)
    assert result.cover_boundary.end_line is not None
