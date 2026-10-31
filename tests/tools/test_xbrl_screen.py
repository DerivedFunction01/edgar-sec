"""Corpus screen smoke specimens over two SP100 bundles."""

from pathlib import Path

from edgar_sec.tools.xbrl_screen import run_screen

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_screen_two_filers_rows_and_census() -> None:
    """ORCL and HON answer RPO from undimensioned totals, slices aside."""
    report = run_screen(_FIXTURES, firms={"ORCL", "HON"})
    assert report["filer_count"] == 2
    rpo = report["panels"]["rpo"]
    assert len(rpo["rows"]) == 2
    values = {row["filer"]: row["value"] for row in rpo["rows"]}
    assert values == {"ORCL": 97_900_000_000.0, "HON": 35_277_000_000.0}
    assert report["census"]["rpo"]["undimensioned"] == 2
    hon_facts = report["specimens"]["HON"]
    assert any(fact["dimensions"] == {} for fact in hon_facts)
    assert any(
        "us-gaap:StatementBusinessSegmentsAxis" in fact["dimensions"]
        for fact in hon_facts
    )
