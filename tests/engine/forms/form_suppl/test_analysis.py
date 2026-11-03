"""Tests for the SUPPL review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_suppl.analysis import analyze_case, summarize_cases

_SUPPL_F10 = """Filed Pursuant to General
Instruction II.L of Form F-10
File No. 333-287547
PRELIMINARY PROSPECTUS SUPPLEMENT
to the Short Form Base Shelf Prospectus dated May 23, 2025
NEW FOUND GOLD CORP.
Common Shares
This prospectus supplement qualifies the distribution of common
shares under the base shelf prospectus.
RISK FACTORS
Investing in our securities involves risks.
USE OF PROCEEDS
The net proceeds will be used for general corporate purposes.
"""

_SUPPL_F9 = """Filed pursuant to General Instruction II.K of Form F-9
File No. 333-109392
PRICING SUPPLEMENT
to the base shelf prospectus dated June 15, 2011
ROYAL BANK OF CANADA
Senior Medium-Term Notes
Pricing terms for the notes offered hereby.
"""


def _case(tmp_path: Path, text: str) -> Path:
    case_dir = tmp_path / f"case-{abs(hash(text)) % 99999}"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(text, encoding="utf-8")
    return case_dir


def test_analyze_suppl_f10_caption(tmp_path: Path) -> None:
    """The II.L caption resolves base form F-10, kind, and date chain."""
    report = analyze_case(_case(tmp_path, _SUPPL_F10), {"form": "SUPPL"})
    assert report is not None
    fields = report["form_suppl"]
    assert fields["base_form"] == "F-10"
    assert fields["file_number"] == "333-287547"
    assert fields["supplement_kind"] == "preliminary prospectus supplement"
    assert fields["base_prospectus_date"] == "May 23, 2025"
    assert "risk factors" in fields["prospectus_headings"]
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_base_form" not in kinds
    assert "missing_file_number" not in kinds
    assert "missing_supplement_kind" not in kinds


def test_analyze_suppl_f9_pricing(tmp_path: Path) -> None:
    """The II.K caption resolves base form F-9 and the pricing kind."""
    report = analyze_case(_case(tmp_path, _SUPPL_F9), {"form": "SUPPL"})
    assert report is not None
    fields = report["form_suppl"]
    assert fields["base_form"] == "F-9"
    assert fields["file_number"] == "333-109392"
    assert fields["supplement_kind"] == "pricing supplement"
    assert fields["base_prospectus_date"] == "June 15, 2011"


def test_analyze_suppl_era_caption_variants(tmp_path: Path) -> None:
    """Era typesetting variants of the instruction caption resolve."""
    for caption, base in (
        ("Instruction ILL of F-10", "F-10"),
        ("Instruction II.K of Form-9", "F-9"),
        ("Instruction II. L. of Form F-10", "F-10"),
    ):
        text = _SUPPL_F10.replace("Instruction II.L of Form F-10", caption)
        report = analyze_case(_case(tmp_path, text), {"form": "SUPPL"})
        assert report is not None
        assert report["form_suppl"]["base_form"] == base


def test_summarize_cases_scorecard(tmp_path: Path) -> None:
    """The summary aggregates the caption census."""
    reports = [
        analyze_case(_case(tmp_path, _SUPPL_F10), {"form": "SUPPL"}),
        analyze_case(_case(tmp_path, _SUPPL_F9), {"form": "SUPPL"}),
    ]
    summary = summarize_cases([r for r in reports if r is not None])
    card = summary["form_suppl_scorecard"]
    assert card["case_count"] == 2
    assert card["base_form_counts"] == {"F-10": 1, "F-9": 1}
    assert card["file_number_count"] == 2
