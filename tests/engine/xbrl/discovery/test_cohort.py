"""Tests for seed cohort definitions and loading."""

from edgar_sec.engine.xbrl.discovery.cohort import load_seed_cohort
from tests.support import fixture_path


def test_load_seed_cohort_from_fixture() -> None:
    """Verify loading from explicit fixture path and field constraints."""
    cohort = load_seed_cohort(fixture_path("xbrl/seed_cohort.json"))
    assert len(cohort) == 40
    assert cohort[0].firm == "MSFT"
    assert cohort[1].firm == "AAPL"
    for filing in cohort:
        assert len(str(filing.accession)) == 20
        assert int(filing.cik) > 0
        assert filing.form in ("10-K", "20-F")
        assert filing.fy in (2022, 2023, 2024)


def test_load_sp100_cohort_from_fixture() -> None:
    """Verify loading 100 firms across GICS sectors from sp100 fixture."""
    cohort = load_seed_cohort(fixture_path("xbrl/taxonomy/sp100_cohort.json"))
    assert len(cohort) == 100
    firms = {f.firm for f in cohort}
    assert "AAPL" in firms
    assert "MSFT" in firms
    assert "JPM" in firms
    assert "NVDA" in firms
    for filing in cohort:
        assert len(str(filing.accession)) == 20
        assert int(filing.cik) > 0
        assert filing.form == "10-K"
