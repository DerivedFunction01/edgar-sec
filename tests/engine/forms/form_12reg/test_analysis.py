from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_12reg.analysis import analyze_case, summarize_cases

_SAMPLE_25_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM 25
NOTIFICATION OF REMOVAL FROM LISTING AND/OR REGISTRATION UNDER SECTION 12(b) OF THE SECURITIES EXCHANGE ACT OF 1934.
Commission File Number: 001-11288
ACME WIDGETS CORP. The NASDAQ Stock Market LLC
(Exact name of Issuer as specified in its charter, and name of Exchange where security is listed and/or registered)
100 Main Street, Springfield, Illinois 62701 (217) 555-0100
(Address, including zip code, and telephone number, including area code, of Issuer's principal executive offices)
Common Stock, par value $0.01 per share
(Description of class of securities)
Please place an X in the box to designate the rule provision relied upon to strike the class of securities from listing and registration:
x 17 CFR 240.12d2-2(a)(1)
  17 CFR 240.12d2-2(a)(2)
  17 CFR 240.12d2-2(a)(3)
  17 CFR 240.12d2-2(a)(4)
  Pursuant to 17 CFR 240.12d2-2(b), the Exchange has complied with its rules to strike the class of securities from listing and/or withdraw registration on the Exchange.
  Pursuant to 17 CFR 240.12d2-2(c), the Issuer has complied with the rules of the Exchange and the requirements of 17 CFR 240.12d2-2(c).
"""

_SAMPLE_8A_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM 8-A
FOR REGISTRATION OF CERTAIN CLASSES OF SECURITIES PURSUANT TO SECTION 12(b) OR (g) OF THE SECURITIES EXCHANGE ACT OF 1934
ACME WIDGETS CORP.
(Exact name of registrant as specified in charter)
Delaware 38-0000000
(State or Other Jurisdiction of Incorporation or Organization) (I.R.S. Employer Identification No.)
100 Main Street, Springfield, Illinois 62701
(Address of Registrant's Principal Executive Offices) (ZIP Code)
Securities to be registered pursuant to Section 12(b) of the Act:
Title of each class to be so registered
Name of each exchange on which each class is to be registered
Common Stock, par value $0.01 per share
The Nasdaq Stock Market LLC
If this form relates to the registration of a class of securities pursuant to Section 12(b) of the Exchange Act and is effective pursuant to General Instruction A.(c) or (e), check the following box. [X]
If this form relates to the registration of a class of securities pursuant to Section 12(g) of the Exchange Act and is effective pursuant to General Instruction A.(d) or (e), check the following box. [ ]
Securities Act registration statement or Regulation A offering statement file number to which this form relates: 333-284008
Securities to be registered pursuant to Section 12(g) of the Act: None.
INFORMATION REQUIRED IN REGISTRATION STATEMENT
Item 1. Description of Registrant's Securities to be Registered
The common stock is described here.
Item 2. Exhibits
Exhibits are listed here.
"""


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_form_25_notification(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_25_TEXT)
    result = analyze_case(tmp_path, {"accession": "0000006955-22-000016", "form": "25"})
    assert result is not None
    fields = result["form_12reg"]
    assert fields["kind"] == "notification"
    assert fields["commission_file_number"] == "001-11288"
    assert fields["issuer_name"] is not None
    assert result["checkmarks"]["rule_12d2_2_a1"] is True
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "no_rule_provision_checked" not in kinds
    assert "missing_commission_file_number" not in kinds


def test_analyze_form_8a_registration(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_8A_TEXT)
    result = analyze_case(
        tmp_path, {"accession": "0000006955-22-000017", "form": "8-A12B"}
    )
    assert result is not None
    fields = result["form_12reg"]
    assert fields["kind"] == "registration"
    assert fields["registrant_name"] == "ACME WIDGETS CORP."
    assert fields["security_classes"] == [
        {
            "class_title": "Common Stock, par value $0.01 per share",
            "exchange": "The Nasdaq Stock Market LLC",
        }
    ]
    assert fields["related_file_number"] == "333-284008"
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_registrant_name" not in kinds
    assert "missing_security_class" not in kinds


def test_summarize_counts_kinds(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_25_TEXT)
    rep = analyze_case(tmp_path, {"accession": "0000006955-22-000016", "form": "25"})
    assert rep is not None
    summary = summarize_cases([rep])
    scorecard = summary["form_12reg_scorecard"]
    assert scorecard["kind_counts"] == {"notification": 1}
    assert scorecard["rule_checked_counts"]["rule_12d2_2_a1"] == 1
