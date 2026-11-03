"""Tests for shared form case analysis and scorecard aggregation."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    reinfer_unmasked_checkmarks,
    summarize_form_cases,
)

_SAMPLE_10K_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM 10-K
ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934
ACME CORP
(Exact name of registrant as specified in its charter)
Large accelerated filer [X]   Accelerated filer [ ]   Non-accelerated filer [ ]
Item 1. Business
Acme designs and manufactures advanced widgets.
Item 1A. Risk Factors
Our operations involve operational risks.
Item 7. Management's Discussion and Analysis of Financial Condition
Results of operations improved significantly.
Item 8. Financial Statements and Supplementary Data
Note 1. Summary of Accounting Policies
The financial statements have been prepared in accordance with GAAP.
Note 2. Revenues
Revenues are recognized when control transfers.
"""


def test_reinfer_unmasked_checkmarks_merges_without_downgrade() -> None:
    text = (
        "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\n"
        "SCHEDULE 14A\n"
        "Check the appropriate box:\n"
        "<TABLE>\n[X] Definitive Proxy Statement\n</TABLE>\n"
        "<TABLE>\n[ ] Preliminary Proxy Statement\n</TABLE>\n"
        "Notice of Annual Meeting\nThe board of directors recommends a vote.\n"
    )
    rep: dict = {
        "checkmarks": {
            "candidate_states": {"classification_preliminary": "checked"},
            "checked_keys": ("classification_preliminary",),
        }
    }
    reinfer_unmasked_checkmarks(text, rep, family="14A")
    states = rep["checkmarks"]["candidate_states"]
    assert states["classification_definitive"] == "checked"
    assert states["classification_preliminary"] == "checked"
    assert "classification_definitive" in rep["checkmarks"]["checked_keys"]


def test_locate_text_artifact_finds_preferred(tmp_path: Path) -> None:
    ops = tmp_path / "operations"
    ops.mkdir()
    render_txt = ops / "render_to_txt.txt"
    render_txt.write_text("sample", encoding="utf-8")
    assert locate_text_artifact(tmp_path) == render_txt


def test_locate_text_artifact_missing(tmp_path: Path) -> None:
    assert locate_text_artifact(tmp_path) is None


def test_analyze_form_case_10k(tmp_path: Path) -> None:
    ops = tmp_path / "operations"
    ops.mkdir()
    (ops / "render_to_txt.txt").write_text(_SAMPLE_10K_TEXT, encoding="utf-8")

    record = {"accession": "0000001000-24-000001", "form": "10-K"}
    rep = analyze_form_case(tmp_path, record)
    assert rep is not None
    assert rep["form"] == "10-K"
    assert rep["family"] == "10-K"
    assert rep["checkmarks"]["filer_status"] == "large_accelerated_filer"
    assert "ITEM 1" in rep["taxonomy"]["detected_items"]
    assert "ITEM 1A" in rep["taxonomy"]["detected_items"]
    assert "NOTE 1" in rep["notes"]["detected_notes"]


def test_summarize_form_cases(tmp_path: Path) -> None:
    ops = tmp_path / "operations"
    ops.mkdir()
    (ops / "render_to_txt.txt").write_text(_SAMPLE_10K_TEXT, encoding="utf-8")

    record = {"accession": "0000001000-24-000001", "form": "10-K"}
    rep = analyze_form_case(tmp_path, record)
    assert rep is not None

    summary = summarize_form_cases([rep], family="10-K")
    assert summary["case_count"] == 1
    assert (
        summary["checkmark_scorecard"]["filer_status_counts"]["large_accelerated_filer"]
        == 1
    )
    assert "ITEM 1" in summary["taxonomy_scorecard"]["item_coverage"]


def test_anomaly_record_shape() -> None:
    assert anomaly_record("missing_field", "no value matched") == {
        "kind": "missing_field",
        "details": "no value matched",
        "detail": "no value matched",
    }
