from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.registration.analysis import (
    analyze_case,
    summarize_cases,
)

_SAMPLE_S1_TEXT = """\
FORM S-1
REGISTRATION STATEMENT UNDER THE SECURITIES ACT OF 1933
ACME CORP
(Exact name of registrant as specified in its charter)
Delaware
(State or other jurisdiction of incorporation or organization)
1234
(Primary Standard Industrial Classification Code Number)
12-3456789
(I.R.S. Employer Identification Number)
100 Main Street, New York, NY 10001
(Address, including zip code, and telephone number, including area code)
John Doe, 100 Main Street, New York, NY 10001
(Name, address, including zip code, and telephone number, including area code)
Approximate date of commencement of proposed sale to the public: As soon as practicable.
[X] If any of the securities being registered on this Form are to be offered on a delayed or continuous basis pursuant to Rule 415 under the Securities Act of 1933
[ ] If this Form is filed to register additional securities for an offering pursuant to Rule 462(b)
Large accelerated filer [X]   Accelerated filer [ ]   Non-accelerated filer [ ]
Emerging growth company [ ]
CALCULATION OF REGISTRATION FEE
Title of each class of securities to be registered: Common Stock
Amount to be registered: 1,000,000
Proposed maximum offering price per share: $10.00
Proposed maximum aggregate offering price: $10,000,000
Amount of registration fee: $1,298
TABLE OF CONTENTS
PROSPECTUS SUMMARY
This summary highlights information appearing elsewhere in this prospectus.
We are a leading provider of innovative widgets. We have generated substantial revenue.
Our business has grown significantly across multiple segments.
RISK FACTORS
Investing in our securities involves a high degree of risk.
USE OF PROCEEDS
We intend to use the net proceeds from this offering for general corporate purposes.
DILUTION
Our net tangible book value per share as of December 31 was $1.00.
EXHIBITS AND FINANCIAL STATEMENT SCHEDULES
Item 16. Exhibits.
"""


def test_analyze_case_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_case_valid_synthetic(tmp_path: Path) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    txt_path = ops / "render_to_txt.txt"
    txt_path.write_text(_SAMPLE_S1_TEXT, encoding="utf-8")

    result = analyze_case(tmp_path, {"accession": "0000123456-23-000001"})
    assert result is not None
    assert result["accession"] == "0000123456-23-000001"
    assert result["form"] == "S-1"
    assert result["boundary"]["confidence"] >= 0.7
    assert result["boundary"]["end_line"] > 15
    assert result["checkmarks"]["rule_415"] is True
    assert result["checkmarks"]["filer_status"] == "large_accelerated_filer"
    assert "rule_415" in result["checkmarks"]["checked_keys"]
    assert "corridor" in result
    assert result["taxonomy"]["item_count"] > 0


def test_summarize_cases_empty() -> None:
    summary = summarize_cases([])
    assert summary["case_count"] == 0
    assert summary["family"] == "S-1"


def test_summarize_cases_aggregation(tmp_path: Path) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(_SAMPLE_S1_TEXT, encoding="utf-8")

    report = analyze_case(tmp_path, {"accession": "0000123456-23-000001"})
    assert report is not None

    summary = summarize_cases([report])
    assert summary["case_count"] == 1
    assert summary["boundary_scorecard"]["confidence_tiers"]["high"] == 1
    assert summary["checkmark_scorecard"]["rule_415_count"] == 1
    assert (
        summary["checkmark_scorecard"]["filer_status_counts"]["large_accelerated_filer"]
        == 1
    )
    assert summary["checkmark_scorecard"]["checked_counts"]["rule_415"] == 1
    assert "corridor_scorecard" in summary
    assert summary["corridor_scorecard"]["leak_case_count"] == 0
    assert summary["taxonomy_scorecard"]["mean_items_per_case"] > 0
