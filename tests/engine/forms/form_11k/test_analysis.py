from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_11k.analysis import analyze_case, summarize_cases

_SAMPLE_11K_TEXT = """UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549

FORM 11-K

[X] ANNUAL REPORT PURSUANT TO SECTION 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934

For the fiscal year ended December 31, 2024

OR

[ ] TRANSITION REPORT PURSUANT TO SECTION 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934

For the transition period from _______ to _______

Commission file number: 001-39187

A. Full title of the plan:

ACME RETIREMENT SAVINGS PLAN

B. Name of issuer of the securities held pursuant to the plan and the address of its
principal executive office:

ACME WIDGETS INC.
100 Main Street, Anytown, ST 12345

FINANCIAL STATEMENTS AND SUPPLEMENTAL SCHEDULES

REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM

We have audited the accompanying statements of net assets available for
benefits of the Plan as of December 31, 2024 and 2023, and the related
statement of changes in net assets available for benefits for the year
ended December 31, 2024.

STATEMENTS OF NET ASSETS AVAILABLE FOR BENEFITS

Assets held for investment purposes were one hundred twenty million
dollars at the end of the plan year, and participant loans receivable
were four million dollars.

STATEMENT OF CHANGES IN NET ASSETS AVAILABLE FOR BENEFITS

Contributions from participants and the employer, together with net
investment income, increased the net assets available for benefits
during the year, while benefit payments to participants decreased
them.

NOTES TO FINANCIAL STATEMENTS

The Plan is a defined contribution plan covering substantially all
employees of the issuer, and contributions are invested as directed
by participants among the available investment options.

SIGNATURES

Pursuant to the requirements of the Securities Exchange Act of 1934, the Plan
Administrator has duly caused this annual report to be signed on its behalf by
the undersigned hereunto duly authorized.

ACME RETIREMENT SAVINGS PLAN

By: /s/ Jane Doe
Jane Doe, Plan Administrator
Date: June 20, 2025
"""


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_case_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_case_valid_synthetic(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_11K_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000000000-25-000001", "form": "11-K"}
    )
    assert result is not None
    assert result["family"] == "11-K"
    fields = result["form_11k"]
    assert fields["commission_file_number"] == "001-39187"
    assert fields["plan_title"] == "ACME RETIREMENT SAVINGS PLAN"
    assert fields["issuer_name"] is not None
    assert "ACME" in fields["issuer_name"]
    assert fields["fiscal_year_end"] == "December 31, 2024"
    assert "ITEM 4" in fields["detected_items"]
    assert fields["statements_present"] is True
    assert fields["signature"]["present"] is True
    assert result["checkmarks"]["report_annual"] is True
    assert result["checkmarks"]["report_transition"] is False
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_commission_file_number" not in kinds
    assert "missing_plan_title" not in kinds
    assert "missing_issuer_name" not in kinds
    assert "no_report_type_checked" not in kinds
    assert "missing_signature" not in kinds


def test_analyze_case_table_wrapped_report_boxes(tmp_path: Path) -> None:
    text = _SAMPLE_11K_TEXT.replace(
        "[X] ANNUAL REPORT PURSUANT TO SECTION 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934",
        "<TABLE>\n[X] ANNUAL REPORT PURSUANT TO SECTION 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934\n</TABLE>",
    ).replace(
        "[ ] TRANSITION REPORT PURSUANT TO SECTION 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934",
        "<TABLE>\n[ ] TRANSITION REPORT PURSUANT TO SECTION 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934\n</TABLE>",
    )
    _write_case(tmp_path, text)

    result = analyze_case(
        tmp_path, {"accession": "0000000000-25-000001", "form": "11-K"}
    )
    assert result is not None
    assert result["checkmarks"]["report_annual"] is True
    assert result["checkmarks"]["report_transition"] is False
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "no_report_type_checked" not in kinds


def test_analyze_case_long_document_boundary(tmp_path: Path) -> None:
    paragraphs = []
    for index in range(40):
        paragraphs.append(
            f"Note {index}. The financial statements present the net assets "
            "available for benefits and the audited plan investments, "
            "contributions, and participant accounts in accordance with "
            "accounting principles, as examined by the independent auditors."
        )
    text = _SAMPLE_11K_TEXT + "\n" + "\n\n".join(paragraphs) + "\n"
    _write_case(tmp_path, text)

    result = analyze_case(
        tmp_path, {"accession": "0000000000-25-000001", "form": "11-K"}
    )
    assert result is not None
    assert result["boundary"]["method"] != "unknown"
    assert result["cover_lines"] > 0
    assert result["checkmarks"]["report_annual"] is True


def test_analyze_case_section_15_dash_d_variant(tmp_path: Path) -> None:
    text = _SAMPLE_11K_TEXT.replace(
        "SECTION 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934",
        "SECTION 15-(d) OF THE SECURITIES EXCHANGE ACT OF 1934",
    )
    _write_case(tmp_path, text)

    result = analyze_case(
        tmp_path, {"accession": "0000000000-25-000001", "form": "11-K"}
    )
    assert result is not None
    assert result["checkmarks"]["report_annual"] is True


def test_analyze_case_signature_plural_anchor(tmp_path: Path) -> None:
    text = _SAMPLE_11K_TEXT.replace(
        "the Plan\nAdministrator has duly caused this annual report",
        "the trustees (or other persons who administer the employee benefit plan)\nhave duly caused this annual report",
    )
    _write_case(tmp_path, text)

    result = analyze_case(
        tmp_path, {"accession": "0000000000-25-000001", "form": "11-K"}
    )
    assert result is not None
    assert result["form_11k"]["signature"]["present"] is True


def test_summarize_cases_aggregates_scorecard(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_11K_TEXT)
    report = analyze_case(
        tmp_path, {"accession": "0000000000-25-000001", "form": "11-K"}
    )
    assert report is not None
    summary = summarize_cases([report])
    card = summary["form_11k_scorecard"]
    assert card["commission_file_number_count"] == 1
    assert card["plan_title_count"] == 1
    assert card["report_checked_counts"]["report_annual"] == 1
    assert card["item_coverage"]["ITEM 4"] == 1
    assert card["statements_present_count"] == 1
    assert card["signature_present_count"] == 1
