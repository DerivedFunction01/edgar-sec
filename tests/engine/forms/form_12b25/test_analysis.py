from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_12b25.analysis import analyze_case, summarize_cases

_SAMPLE_NT_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM 12b-25
NOTIFICATION OF LATE FILING
SEC FILE NUMBER: 001-12777
CUSIP NUMBER: 002474104
(Check one):
Form 10-K [X]   Form 20-F [ ]   Form 11-K [ ]
Form 10-Q [ ]   Form 10-D [ ]   Form N-CEN [ ]
Form N-CSR [ ]
For Period Ended: February 28, 2018
Transition Report on Form 10-K [ ]
Transition Report on Form 20-F [ ]
Transition Report on Form 11-K [ ]
Transition Report on Form 10-Q [ ]
For the Transition Period Ended:
PART I — REGISTRANT INFORMATION
ACME INC.
Full Name of Registrant
One Museum Place, 3100 W 7th Street
Address of Principal Executive Office (Street and Number)
Fort Worth, Texas 76107
City, State and Zip Code
PART II — RULES 12b-25(b) AND (c)
If the subject report could not be filed without unreasonable effort or expense and the registrant seeks relief pursuant to Rule 12b-25(b), the following should be completed. (Check box if appropriate)
(a) The reason described in reasonable detail in Part III of this form could not be eliminated without unreasonable effort or expense [X]
(b) The subject annual report will be filed on or before the fifteenth calendar day following the prescribed due date [ ]
(c) The accountant's statement or other exhibit required by Rule 12b-25(c) has been attached if applicable [ ]
PART III — NARRATIVE
State below in reasonable detail why Forms 10-K, 20-F, 11-K, 10-Q, 10-D, N-CEN, N-CSR, or the transition report or portion thereof, could not be filed within the prescribed time period.
The Company has determined that it is unable to file its Annual Report on Form 10-K for the fiscal year ended February 28, 2018 within the prescribed time period because the audit of its financial statements remains incomplete.
PART IV — OTHER INFORMATION
(1) Name and telephone number of person to contact in regard to this notification
John Smith
(212) 555-0147
(Name) (Area Code) (Telephone Number)
(2) Have all other periodic reports required under Section 13 or 15(d) of the Securities Exchange Act of 1934 during the preceding 12 months been filed? Yes [X] No [ ]
(3) Is it anticipated that any significant change in results of operations from the corresponding period for the last fiscal year will be reflected by the earnings statements? Yes [ ] No [X]
ACME INC. has caused this notification to be signed on its behalf by the undersigned hereunto duly authorized.
Date: March 15, 2018
By: /s/ John Smith
John Smith, Chief Financial Officer
"""


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_case_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_case_valid_synthetic(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_NT_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000008947-18-000049", "form": "NT 10-K"}
    )
    assert result is not None
    assert result["family"] == "12B-25"
    fields = result["form_12b25"]
    assert fields["sec_file_number"] == "001-12777"
    assert fields["cusip"] == "002474104"
    assert fields["subject_form"] == "10-K"
    assert fields["transition_form"] is None
    assert fields["part1_registrant_name"] == "ACME INC."
    assert fields["part3_narrative_words"] >= 10
    assert fields["part4"]["contact_name"] == "John Smith"
    assert fields["part4"]["contact_phone"] == "212-555-0147"
    assert fields["part4"]["q2_answer"] == "yes"
    assert fields["part4"]["q3_answer"] == "no"
    assert fields["signature"]["present"] is True
    assert fields["signature"]["conformed"] is True
    assert result["checkmarks"]["subject_10k"] is True
    assert result["checkmarks"]["part2_a"] is True
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_sec_file_number" not in kinds
    assert "no_subject_report_checked" not in kinds
    assert "missing_part1_registrant" not in kinds
    assert "missing_part3_narrative" not in kinds
    assert "missing_part4_contact" not in kinds
    assert "missing_part4_q2_answer" not in kinds
    assert "missing_part4_q3_answer" not in kinds
    assert "missing_signature" not in kinds


_TABLE_NT_TEXT = """\
U.S. SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM 12b-25
NOTIFICATION OF LATE FILING
SEC FILE NO. 001-40233
CUSIP NO. 02369M102
[ ] Form 10-K  [ ] Form 20-F  [ ] Form 11-K  [X] Form 10-Q and Form 10-D  [ ] Form N-SAR  [ ] Form N-CSR
For Period Ended: September 30, 2024
[ ]  Transition Report on Form 10-K
For the Transition Period Ended:
Part I - Registrant Information
<TABLE>
Full Name of Registrant:                Royalty Example Holding Corp
Former Name if Applicable:              Example Acquisition Inc
Address of Principal Executive Office:  12115 Visionary Way, Fishers, IN 46038
</TABLE>
Part II - Rules 12b-25(b) and (c)
If the subject report could not be filed without unreasonable effort or expense and the registrant seeks relief pursuant to Rule 12b-25(b), the following should be completed. (Check box if appropriate)
(a) The reason described in reasonable detail in Part III of this form could not be eliminated without unreasonable effort or expense [X]
Part III – Narrative
State below in reasonable detail why Forms 10-K, 20-F, 11-K, 10-Q, 10-D, N-SAR, N-CSR, or the transition report or portion thereof, could not be filed within the prescribed time period.
The Registrant's Quarterly Report on Form 10-Q for the period ending September 30, 2024 could not be filed within the prescribed time period because the required financial statements could not be completed in a timely manner without unreasonable effort and expense.
Part IV - Other Information
1. Name and telephone number of person to contact in regard to this notification.
<TABLE>
Thomas M. Sauve  317-855-9926
</TABLE>
2. Have all other periodic reports required under section 13 or 15(d) of the Securities Exchange Act of 1934 during the preceding 12 months been filed? If the answer is no, identify report(s). [X] Yes [ ] No
3. Is it anticipated that any significant change in result of operations from the corresponding period for the last fiscal year will be reflected by the earnings statements to be included in the subject report or portion thereof? [ ] Yes [X] No
Royalty Example Holding Corp has caused this notification to be signed on its behalf by the undersigned hereunto duly authorized.
Date: November 14, 2024
By:   /s/ Thomas M. Sauve
Chief Executive Officer
"""


def test_analyze_case_table_layout_variants(tmp_path: Path) -> None:
    _write_case(tmp_path, _TABLE_NT_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0001477932-24-007209", "form": "NT 10-Q"}
    )
    assert result is not None
    fields = result["form_12b25"]
    assert fields["sec_file_number"] == "001-40233"
    assert fields["cusip"] == "02369M102"
    assert fields["part1_registrant_name"] == "Royalty Example Holding Corp"
    assert fields["part3_narrative_words"] >= 10
    assert fields["part4"]["contact_name"] == "Thomas M. Sauve"
    assert fields["part4"]["contact_phone"] == "317-855-9926"
    assert fields["part4"]["q2_answer"] == "yes"
    assert fields["part4"]["q3_answer"] == "no"
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_sec_file_number" not in kinds
    assert "missing_part1_registrant" not in kinds
    assert "missing_part3_narrative" not in kinds
    assert "missing_part4_contact" not in kinds
    assert "missing_part4_q2_answer" not in kinds
    assert "missing_part4_q3_answer" not in kinds


_CONVENTION_NT_TEXT = """\
U.S. SECURITIES AND EXCHANGE COMMISSION
FORM 12b-25
NOTIFICATION OF LATE FILING
SEC FILE NO. 0-22636
PART I--REGISTRANT INFORMATION
ICTS Example, N.V.
------------------------
Full Name of Registrant
PART IV-- OTHER INFORMATION
(1) Name and telephone number of person in regard to this notification
David W. Sass, Esq.         (212)            448-1100
(2) Have all other periodic reports required under Section 13 or 15(d) of the Securities Exchange Act of 1934 during the preceding 12 months been filed? If answer no, identify report(s).                       [X]  Yes       No
(3) Is it anticipated that any significant change in results of operations from the corresponding period for the last fiscal year will be reflected by the earnings statements to be included in the subject report or portion thereof?
                                                                  Yes      [X]  No
ICTS Example, N.V. has caused this notification to be signed on its behalf by the undersigned hereunto duly authorized.
Date  June 29, 2010      By: /s/ Avraham Dan
"""


def test_analyze_case_part4_mark_first_convention(tmp_path: Path) -> None:
    _write_case(tmp_path, _CONVENTION_NT_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000891092-10-002632", "form": "NT 10-K"}
    )
    assert result is not None
    fields = result["form_12b25"]
    assert fields["sec_file_number"] == "0-22636"
    assert fields["part1_registrant_name"] == "ICTS Example"
    assert fields["part4"]["contact_name"] == "David W. Sass, Esq."
    assert fields["part4"]["contact_phone"] == "212-448-1100"
    assert fields["part4"]["q2_answer"] == "yes"
    assert fields["part4"]["q3_answer"] == "no"


def test_analyze_case_part1_last_section_no_crash(tmp_path: Path) -> None:
    text = (
        "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\n"
        "FORM 12b-25\nNOTIFICATION OF LATE FILING\n"
        "SEC FILE NUMBER: 001-12777\n"
        "PART I — REGISTRANT INFORMATION\nACME INC.\n"
        "Full Name of Registrant\n"
    )
    _write_case(tmp_path, text)

    result = analyze_case(
        tmp_path, {"accession": "0000008947-18-000050", "form": "NT 10-K"}
    )
    assert result is not None
    assert result["form_12b25"]["part1_registrant_name"] == "ACME INC."


def test_summarize_cases_empty() -> None:
    summary = summarize_cases([])
    assert summary["case_count"] == 0
    assert summary["family"] == "12B-25"


def test_summarize_cases_scorecard(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_NT_TEXT)
    rep = analyze_case(
        tmp_path, {"accession": "0000008947-18-000049", "form": "NT 10-K"}
    )
    assert rep is not None
    summary = summarize_cases([rep])
    assert summary["family"] == "12B-25"
    scorecard = summary["form_12b25_scorecard"]
    assert scorecard["sec_file_number_count"] == 1
    assert scorecard["cusip_count"] == 1
    assert scorecard["subject_form_counts"]["10-K"] == 1
    assert scorecard["part2_checked_counts"]["part2_a"] == 1
    assert scorecard["part4_q2_answer_counts"]["yes"] == 1
    assert scorecard["part4_q3_answer_counts"]["no"] == 1
    assert scorecard["signature_conformed_count"] == 1
