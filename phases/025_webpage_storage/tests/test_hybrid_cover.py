"""Unit and integration tests for HybridCoverPreprocessor."""

from __future__ import annotations

import importlib

shared_mod = importlib.import_module(
    "phases.025_webpage_storage.processors.forms.shared.hybrid_cover"
)
HybridCoverPreprocessor = shared_mod.HybridCoverPreprocessor


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
    assert (
        "Delaware\n(State or other jurisdiction of incorporation or organization)"
        in text
    )
    assert "35-1828377\n(I.R.S. Employer Identification No.)" in text

    # Check address & zip inlined
    assert "1800 North Military Trail, Boca Raton, FL 33431" in text
    assert "(Address of principal executive offices) (Zip Code)" in text


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
    assert "Large accelerated filer [X]" in text
    assert "Accelerated filer [ ]" in text
    assert "Non-accelerated filer [ ]" in text
    assert "Smaller reporting company [ ]" in text
