from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_14a.analysis import analyze_case, summarize_cases

_SAMPLE_14A_TEXT = """\
UNITED STATES

SECURITIES AND EXCHANGE COMMISSION

Washington, D.C. 20549

SCHEDULE 14A INFORMATION

Proxy Statement Pursuant to Section 14(a) of the Securities Exchange Act of 1934

Filed by the Registrant [X]

Filed by a Party other than the Registrant [ ]

Check the appropriate box:

[ ] Preliminary Proxy Statement

[ ] Confidential, for Use of the Commission Only (as permitted by Rule 14a-6(e)(2))

[X] Definitive Proxy Statement

[ ] Definitive Additional Materials

[ ] Soliciting Material Pursuant to §240.14a-12

ACME WIDGETS CORP.

(Name of Registrant as Specified In Its Charter)

(Name of Person(s) Filing Proxy Statement, if other than the Registrant)

Payment of Filing Fee (Check the appropriate box):

[X] No fee required.

[ ] Fee paid previously with preliminary materials.

[ ] Fee computed on table in exhibit required by Item 25(b) per Exchange Act Rules 14a-6(i)(1) and 0-11.

NOTICE OF ANNUAL MEETING OF STOCKHOLDERS

PROPOSAL 1: ELECTION OF DIRECTORS

The Board of Directors recommends that stockholders elect the nominees named below.

ELECTION OF DIRECTORS

Jane Doe has served as a director since 2020. John Roe has served as a director since 2021.

PROPOSAL 2: ADVISORY VOTE ON EXECUTIVE COMPENSATION

EXECUTIVE COMPENSATION

The following table summarizes the compensation of our named executive officers.

Summary Compensation Table

Name and Principal Position    Year    Salary ($)    Bonus ($)    Stock Awards ($)    Total ($)

Jane Doe, Chief Executive Officer    2025    $600,000    $200,000    $1,000,000    $1,800,000

Jane Doe, Chief Executive Officer    2024    $575,000    $180,000    $900,000    $1,655,000

John Roe, Chief Financial Officer    2025    $400,000    $120,000    $500,000    $1,020,000

CORPORATE GOVERNANCE

The Board has adopted corporate governance guidelines.

OTHER BUSINESS

The Board knows of no other business to be presented at the meeting.
"""


_LONG_BODY_PARAGRAPH = """\
The annual meeting of stockholders will be held for the purpose of electing
directors and ratifying the appointment of the independent registered public
accounting firm. Stockholders of record at the close of business on the record
date are entitled to vote at the meeting, and the board of directors recommends
that stockholders approve each proposal described in this proxy statement.
"""


def _long_case_text() -> str:
    toc = "TABLE OF CONTENTS\nProxy Statement 1\nElection of Directors 2\n"
    body = _LONG_BODY_PARAGRAPH * 40
    return _SAMPLE_14A_TEXT + toc + body


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_case_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_case_valid_synthetic(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_14A_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000006955-25-000016", "form": "DEF 14A"}
    )
    assert result is not None
    assert result["family"] == "14A"
    fields = result["form_14a"]
    assert fields["registrant_name"] == "ACME WIDGETS CORP."
    assert fields["comp_table"]["present"] is True
    assert fields["comp_table"]["row_count"] == 3
    assert fields["proposal_count"] == 2
    assert "ITEM 8" in fields["detected_items"]
    assert result["checkmarks"]["classification_definitive"] is True
    assert result["checkmarks"]["classification_preliminary"] is False
    assert result["checkmarks"]["fee_not_required"] is True
    assert result["checkmarks"]["filed_by_registrant"] is True
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_registrant_name" not in kinds
    assert "no_classification_checked" not in kinds
    assert "no_fee_box_checked" not in kinds
    assert "comp_table_missing" not in kinds


def test_analyze_case_comp_table_after_earlier_mention(tmp_path: Path) -> None:
    filler = "\n".join(
        f"Background discussion paragraph {n} about the committee." for n in range(130)
    )
    text = _SAMPLE_14A_TEXT.replace(
        "EXECUTIVE COMPENSATION\n\nThe following table",
        "Summary Compensation Table\n\n"
        + filler
        + "\n\nEXECUTIVE COMPENSATION\n\nThe following table",
    )
    _write_case(tmp_path, text)

    result = analyze_case(
        tmp_path, {"accession": "0000006955-25-000016", "form": "DEF 14A"}
    )
    assert result is not None
    assert result["form_14a"]["comp_table"]["present"] is True
    assert result["form_14a"]["comp_table"]["row_count"] == 3


def test_analyze_case_table_wrapped_checkboxes(tmp_path: Path) -> None:
    text = _SAMPLE_14A_TEXT.replace(
        "[X] Definitive Proxy Statement",
        "<TABLE>\n[X] Definitive Proxy Statement\n</TABLE>",
    ).replace(
        "[X] No fee required.",
        "<TABLE>\n[X] No fee required.\n</TABLE>",
    )
    _write_case(tmp_path, text)

    result = analyze_case(
        tmp_path, {"accession": "0000006955-25-000016", "form": "DEF 14A"}
    )
    assert result is not None
    assert result["checkmarks"]["classification_definitive"] is True
    assert result["checkmarks"]["fee_not_required"] is True
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "no_classification_checked" not in kinds
    assert "no_fee_box_checked" not in kinds


def test_analyze_case_long_document_boundary(tmp_path: Path) -> None:
    _write_case(tmp_path, _long_case_text())

    result = analyze_case(
        tmp_path, {"accession": "0000006955-25-000016", "form": "DEF 14A"}
    )
    assert result is not None
    assert result["boundary"]["method"] != "unknown"
    assert result["cover_lines"] > 0
    assert result["checkmarks"]["classification_definitive"] is True
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "cover_too_short" not in kinds
    assert "low_confidence_boundary" not in kinds
    assert "no_classification_checked" not in kinds


def test_summarize_cases_scorecard(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_14A_TEXT)
    result = analyze_case(
        tmp_path, {"accession": "0000006955-25-000016", "form": "DEF 14A"}
    )
    assert result is not None
    summary = summarize_cases([result])
    assert summary["case_count"] == 1
    scorecard = summary["form_14a_scorecard"]
    assert scorecard["registrant_name_count"] == 1
    assert scorecard["cases_with_any_classification"] == 1
    assert scorecard["cases_with_any_fee_box"] == 1
    assert scorecard["comp_table_present_count"] == 1
    assert scorecard["comp_table_row_total"] == 3
    assert scorecard["item_coverage"]["ITEM 8"] == 1
