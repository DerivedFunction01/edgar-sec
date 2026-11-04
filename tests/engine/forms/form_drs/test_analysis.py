from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_drs.analysis import (
    analyze_case,
    summarize_cases,
)

_DRS_S1_TEXT = """\
As confidentially submitted to the Securities and Exchange Commission
on June 15, 2026
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
FORM S-1
REGISTRATION STATEMENT
UNDER
THE SECURITIES ACT OF 1933
ACME WIDGETS, INC.
(Exact name of Registrant as specified in its charter)
Delaware
(State or other jurisdiction of incorporation)
36-1234567
(I.R.S. Employer Identification Number)
PROSPECTUS
Acme Widgets, Inc. is offering shares of its common stock.
Risk Factors
Investing in our common stock involves a high degree of risk.
Use of Proceeds
We intend to use the net proceeds for general corporate purposes.
PART II
INFORMATION NOT REQUIRED IN PROSPECTUS
Item 13. Other Expenses of Issuance and Distribution
The following table sets forth the estimated expenses.
Item 17. Undertakings
The undersigned registrant hereby undertakes as follows.
SIGNATURES
Pursuant to the requirements of the Securities Act of 1933, the
registrant has duly caused this registration statement to be signed.
"""

_DRS_2012_TEXT = """\
Confidential Draft Submission No. 2
Amendment No. 1 to Form S-1
This draft registration statement has not been publicly filed with
the Securities and Exchange Commission.
ACME WIDGETS, INC.
Draft Registration Statement
PROSPECTUS
Acme Widgets, Inc. is offering shares of its common stock.
Risk Factors
Investing in our common stock involves a high degree of risk.
SIGNATURES
Pursuant to the requirements of the Securities Act of 1933, the
registrant has duly caused this registration statement to be signed.
"""

_DRSLTR_TEXT = """\
SIMPSON THACHER & BARTLETT LLP
425 LEXINGTON AVENUE
NEW YORK, NY 10017
June 15, 2026
VIA EDGAR
U.S. Securities and Exchange Commission
Division of Corporation Finance
100 F Street, N.E.
Washington, D.C. 20549
Re: Acme Widgets, Inc.
Draft Registration Statement on Form S-1
CIK No. 0001234567
Ladies and Gentlemen:
On behalf of Acme Widgets, Inc., we hereby confidentially submit the
above-referenced Draft Registration Statement.
Sincerely,
Simpson Thacher & Bartlett LLP
"""


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_case_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_drs_submission_dispatches_to_s1(tmp_path: Path) -> None:
    _write_case(tmp_path, _DRS_S1_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0001234567-26-000001", "form": "DRS"}
    )
    assert result is not None
    fields = result["form_drs"]
    assert fields["kind"] == "submission"
    assert fields["banner_present"] is True
    assert fields["base_form"] == "S-1"
    assert fields["base_family"] == "S-1"
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_banner" not in kinds
    assert "missing_base_form" not in kinds


def test_analyze_drs_2012_draft_title(tmp_path: Path) -> None:
    _write_case(tmp_path, _DRS_2012_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0001234567-12-000002", "form": "DRS/A"}
    )
    assert result is not None
    fields = result["form_drs"]
    assert fields["kind"] == "submission"
    assert fields["banner_present"] is True
    assert fields["base_form"] == "S-1"
    assert fields["base_signal"] == "draft_title"
    assert fields["submission_number"] == "2"
    assert fields["amendment_number"] == "1"


def test_analyze_drs_transposed_filed_publicly_legend(tmp_path: Path) -> None:
    text = _DRS_S1_TEXT.replace(
        "As confidentially submitted to the Securities and Exchange Commission",
        "Confidential draft registration statement submitted to the\n"
        "Securities and Exchange Commission on May 14, 2014. This draft\n"
        "registration statement has not been filed publicly with the\n"
        "Securities and Exchange Commission",
    )
    _write_case(tmp_path, text)

    result = analyze_case(
        tmp_path, {"accession": "0001234567-14-000004", "form": "DRS"}
    )
    assert result is not None
    fields = result["form_drs"]
    assert fields["banner_present"] is True
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_banner" not in kinds


def test_analyze_drs_n2_base_form_has_no_dispatch_entry(tmp_path: Path) -> None:
    text = _DRS_S1_TEXT.replace("FORM S-1", "FORM N-2")
    _write_case(tmp_path, text)

    result = analyze_case(
        tmp_path, {"accession": "0001234567-13-000005", "form": "DRS"}
    )
    assert result is not None
    fields = result["form_drs"]
    assert fields["base_form"] == "N-2"
    assert fields["base_family"] is None
    assert fields["dispatch_item_count"] == 0
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_base_form" not in kinds


def test_analyze_drs_20f_base_form_dispatches(tmp_path: Path) -> None:
    text = _DRS_S1_TEXT.replace("FORM S-1", "FORM 20-F/A")
    _write_case(tmp_path, text)

    result = analyze_case(
        tmp_path, {"accession": "0001234567-12-000006", "form": "DRS"}
    )
    assert result is not None
    fields = result["form_drs"]
    assert fields["base_form"] == "20-F"
    assert fields["base_family"] == "20-F"
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_base_form" not in kinds


def test_analyze_drsltr_letter_metadata(tmp_path: Path) -> None:
    _write_case(tmp_path, _DRSLTR_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0001234567-26-000003", "form": "DRSLTR"}
    )
    assert result is not None
    fields = result["form_drs"]
    assert fields["kind"] == "letter"
    assert fields["base_form"] == "S-1"
    assert fields["registrant"] == "Acme Widgets, Inc."
    assert fields["counsel"] == "SIMPSON THACHER & BARTLETT LLP"
    assert fields["letter_date"] == "June 15, 2026"
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_base_form" not in kinds


def test_summarize_cases_aggregates_scorecard(tmp_path: Path) -> None:
    reports = []
    for name, text, accession, form in (
        ("drs", _DRS_S1_TEXT, "0001234567-26-000001", "DRS"),
        ("ltr", _DRSLTR_TEXT, "0001234567-26-000003", "DRSLTR"),
    ):
        case = tmp_path / name
        case.mkdir()
        _write_case(case, text)
        rep = analyze_case(case, {"accession": accession, "form": form})
        assert rep is not None
        reports.append(rep)

    summary = summarize_cases(reports)
    scorecard = summary["form_drs_scorecard"]
    assert scorecard["kind_counts"] == {"submission": 1, "letter": 1}
    assert scorecard["banner_count"] == 1
    assert scorecard["base_form_counts"] == {"S-1": 2}
    assert scorecard["registrant_count"] == 1
    assert scorecard["counsel_count"] == 1
    assert scorecard["letter_date_count"] == 1
