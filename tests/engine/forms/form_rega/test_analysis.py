from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_rega.analysis import analyze_case, summarize_cases
from tests.engine.forms.form_rega.test_xml_parser import _ANNUAL_XML, _OFFERING_XML

_SAMPLE_1U_TEXT = """\
UNITED STATES SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM 1-U
CURRENT REPORT PURSUANT TO REGULATION A
Date of Report (Date of earliest event reported): September 22, 2026 (September 18, 2026)
Commission File No. 024-12195
ALMCO PLUMBING, INC. (Exact name of registrant as specified in its charter)
<TABLE>
           California                       36-4915179
-------------------------------  --------------------------------
(State of other jurisdiction of          (I.R.S. Employer
 incorporation or organization)        Identification No.)
</TABLE>
4838 Ronson Ct, Unit D, San Diego, California 92111
(Full mailing address of principal executive offices)
(858) 209-7214
(Issuer's telephone number, including area code)
Common Stock, par value $0.001 per share
(Title of each class of securities issued pursuant to Regulation A)
Item 1. Fundamental Changes
Change in Control
On September 18, 2026, a change in control of the issuer occurred when the
selling stockholders transferred their shares to the new control person.
Item 9. Other Events
The issuer held its annual meeting of stockholders and elected directors.
SIGNATURES
Pursuant to the requirements of Regulation A, the issuer has duly caused
this report to be signed on its behalf by the undersigned, thereunto duly
authorized, in the City of San Diego, State of California.
"""

_SAMPLE_1SA_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM 1-SA
SEMIANNUAL REPORT PURSUANT TO REGULATION A
For the fiscal semiannual period ended:
June 30, 2026
UC ASSET LP
(Exact name of issuer as specified in its charter)
Delaware 30-0912782
(State of other jurisdiction of incorporation or organization) (I.R.S. Employer Identification No.)
537 Peachtree Street NE, Atlanta GA 30308
(Full mailing address of principal executive offices)
(470) 475-1035
(Issuer's telephone number, including area code)
INFORMATION TO BE INCLUDED IN REPORT
Item 1. Management's Discussion and Analysis of Financial Condition and Results of Operations
Overview of the business and results for the semiannual period.
Item 2. Other Information
None.
Item 3. Financial Statements
INDEX TO FINANCIAL STATEMENTS
Balance sheet and statements of operations for the period.
Item 4. Exhibits
Exhibit index follows.
SIGNATURES
"""

_SAMPLE_1AW_TEXT = """\
GLOW HOLDINGS, INC.
732 S. 6th Street, Suite R Las Vegas, Nevada 89101
September 22, 2026
VIA EDGAR
United States Securities and Exchange Commission
Division of Corporation Finance
100 F Street, N.E. Washington, D.C. 20549
Re: Glow Holdings, Inc.
Offering Statement on Form 1-A Filed September 10, 2026 File No. 024-12814
Ladies and Gentlemen:
Glow Holdings, Inc., a Nevada corporation (the "Company"), hereby respectfully
applies, pursuant to Rule 259 under the Securities Act of 1933, for an order
granting the withdrawal of the Offering Statement on Form 1-A.
The Offering Statement has not been qualified by the Commission.
Very truly yours,
GLOW HOLDINGS, INC.
By: /s/ Daniela Mujica, Chief Executive Officer
"""


def _write_xml_case(tmp_path: Path, payload: bytes) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_xml.xml").write_bytes(payload)


def _write_text_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_offering_xml_case(tmp_path: Path) -> None:
    _write_xml_case(tmp_path, _OFFERING_XML)
    rep = analyze_case(tmp_path, {"accession": "0001663038-26-000001", "form": "1-A"})
    assert rep is not None
    assert rep["anomalies"] == []
    assert rep["form_rega"]["kind"] == "offering"
    assert rep["form_rega"]["tier"] == "Tier 2"


def test_analyze_xml_kind_form_mismatch(tmp_path: Path) -> None:
    _write_xml_case(tmp_path, _ANNUAL_XML)
    rep = analyze_case(tmp_path, {"accession": "0002076148-26-000002", "form": "1-Z"})
    assert rep is not None
    assert any(a.startswith("kind_form_mismatch") for a in rep["anomalies"])


def test_analyze_missing_artifact(tmp_path: Path) -> None:
    rep = analyze_case(tmp_path, {"accession": "0001234567-26-000003", "form": "1-K"})
    assert rep is not None
    assert rep["anomalies"] == ["missing_extracted_xml"]


def test_summarize_xml_counts_kinds(tmp_path: Path) -> None:
    _write_xml_case(tmp_path, _OFFERING_XML)
    rep = analyze_case(tmp_path, {"accession": "0001663038-26-000001", "form": "1-A"})
    assert rep is not None
    summary = summarize_cases([rep])
    assert summary["form_rega_scorecard"]["kind_counts"] == {"offering": 1}
    assert summary["form_rega_scorecard"]["tier_counts"] == {"Tier 2": 1}


def test_analyze_current_text_case(tmp_path: Path) -> None:
    _write_text_case(tmp_path, _SAMPLE_1U_TEXT)
    rep = analyze_case(tmp_path, {"accession": "0001956237-26-000004", "form": "1-U"})
    assert rep is not None
    fields = rep["form_rega"]
    assert fields["kind"] == "current"
    assert fields["issuer_name"] == "ALMCO PLUMBING, INC."
    assert fields["commission_file_number"] == "024-12195"
    assert "ITEM 1" in rep["taxonomy"]["detected_items"]
    assert "ITEM 9" in rep["taxonomy"]["detected_items"]


def test_analyze_semi_annual_text_case(tmp_path: Path) -> None:
    _write_text_case(tmp_path, _SAMPLE_1SA_TEXT)
    rep = analyze_case(tmp_path, {"accession": "0001723517-26-000005", "form": "1-SA"})
    assert rep is not None
    fields = rep["form_rega"]
    assert fields["kind"] == "semi_annual"
    assert fields["issuer_name"] == "UC ASSET LP"
    assert fields["fiscal_period_end"] == "June 30, 2026"
    assert fields["has_fs_index"]


def test_analyze_withdrawal_letter_case(tmp_path: Path) -> None:
    _write_text_case(tmp_path, _SAMPLE_1AW_TEXT)
    rep = analyze_case(tmp_path, {"accession": "0001114859-26-000006", "form": "1-A-W"})
    assert rep is not None
    fields = rep["form_rega"]
    assert fields["kind"] == "withdrawal"
    assert fields["registrant_name"] == "Glow Holdings, Inc."
    assert fields["commission_file_number"] == "024-12814"
    assert fields["withdrawal_statement"]
    kinds = [a["kind"] for a in rep["anomalies"]]
    assert "missing_registrant_name" not in kinds
    assert "missing_withdrawal_statement" not in kinds


def test_analyze_withdrawal_letter_rule477_variant(tmp_path: Path) -> None:
    _write_text_case(
        tmp_path,
        "Nitches, Inc.\n"
        "Request to Withdraw Post-Qualification Amendment on Form 1-A POS\n"
        "Commission File No. 024-12100\n"
        "The Company is withdrawing the Offering Circular.\n",
    )
    rep = analyze_case(tmp_path, {"accession": "0001393905-22-000328", "form": "1-A-W"})
    assert rep is not None
    assert rep["form_rega"]["withdrawal_statement"]
    kinds = [a["kind"] for a in rep["anomalies"]]
    assert "missing_withdrawal_statement" not in kinds
