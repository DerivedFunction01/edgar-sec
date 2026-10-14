"""Tests for seed cohort definitions and loading."""

from edgar_sec.engine.xbrl.cohort import load_seed_cohort
from tests.support import fixture_path


def test_load_seed_cohort_from_fixture() -> None:
    """Verify loading from explicit fixture path and field constraints."""
    cohort = load_seed_cohort(fixture_path("xbrl/seed_cohort.json"))
    assert len(cohort) == 15
    assert cohort[0].firm == "MSFT"
    assert cohort[1].firm == "AAPL"
    for filing in cohort:
        assert len(str(filing.accession)) == 20
        assert int(filing.cik) > 0
        assert filing.form in ("10-K", "20-F")
        assert filing.fy in (2023, 2024)
