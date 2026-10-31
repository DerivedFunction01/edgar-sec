"""Tests for seed cohort definitions and loading."""

from edgar_sec.engine.xbrl.discovery.cohort import (
    canonical_probe_cohort_path,
    canonical_seed_cohort_path,
    canonical_sp100_cohort_path,
    canonical_vintage_cohort_path,
    load_canonical_probe_cohort,
    load_canonical_seed_cohort,
    load_canonical_sp100_cohort,
    load_canonical_union_cohort,
    load_canonical_vintage_cohort,
    load_seed_cohort,
)
from tests.support import fixture_path


def test_canonical_seed_cohort_is_the_registry() -> None:
    """Verify the canonical resolver names the maintained registry file."""
    assert canonical_seed_cohort_path() == fixture_path("xbrl/seed_cohort.json")
    cohort = load_canonical_seed_cohort()
    assert len(cohort) == 49
    assert len({filing.firm for filing in cohort}) == 49


def test_canonical_vintage_cohort_is_the_registry() -> None:
    """Verify the vintage resolver names the measurement-corpus registry."""
    assert canonical_vintage_cohort_path() == fixture_path("xbrl/vintage_cohort.json")
    cohort = load_canonical_vintage_cohort()
    assert len(cohort) == 16
    assert {filing.firm for filing in cohort} == {
        "BAC",
        "MSFT",
        "AAPL",
        "SHEL",
        "BP",
        "NVS",
    }


def test_canonical_sp100_cohort_is_the_registry() -> None:
    """Verify the SP100 resolver names the scale-corpus registry."""
    assert canonical_sp100_cohort_path() == fixture_path("xbrl/sp100_cohort.json")
    cohort = load_canonical_sp100_cohort()
    assert len(cohort) == 60
    assert len({filing.firm for filing in cohort}) == 60


def test_canonical_probe_cohort_is_the_registry() -> None:
    """Verify the probe resolver names the form-probe corpus registry."""
    assert canonical_probe_cohort_path() == fixture_path("xbrl/probe_cohort.json")
    cohort = load_canonical_probe_cohort()
    assert len(cohort) == 7
    assert [f.form for f in cohort].count("10-Q") == 4
    assert [f.form for f in cohort].count("8-K") == 3
    for filing in cohort:
        assert len(str(filing.accession)) == 20
        assert int(filing.cik) > 0
        assert filing.fy == 2026


def test_probe_cohort_stays_outside_the_union() -> None:
    """Verify the probe corpus never joins the seed/vintage/SP100 union."""
    probe_accessions = {str(f.accession) for f in load_canonical_probe_cohort()}
    union_accessions = {str(f.accession) for f in load_canonical_union_cohort()}
    assert probe_accessions.isdisjoint(union_accessions)


def test_canonical_union_cohort_covers_all_registries() -> None:
    """Verify the union loader returns all 125 filings, accessions disjoint."""
    cohort = load_canonical_union_cohort()
    assert len(cohort) == 125
    assert len({str(filing.accession) for filing in cohort}) == 125
    assert len({filing.firm for filing in cohort}) == 112


def test_load_seed_cohort_from_fixture() -> None:
    """Verify loading from explicit fixture path and field constraints."""
    cohort = load_seed_cohort(fixture_path("xbrl/seed_cohort.json"))
    assert len(cohort) == 49
    assert cohort[0].firm == "MSFT"
    assert cohort[1].firm == "AAPL"
    bac = [filing for filing in cohort if filing.firm == "BAC"]
    assert [(filing.fy, str(filing.accession)) for filing in bac] == [
        (2024, "0000070858-25-000139"),
    ]
    assert len({filing.firm for filing in cohort}) == 49
    for filing in cohort:
        assert len(str(filing.accession)) == 20
        assert int(filing.cik) > 0
        assert filing.form in ("10-K", "20-F")
        assert 2011 <= filing.fy <= 2024


def test_load_vintage_cohort_from_fixture() -> None:
    """Verify the vintage registry holds the longitudinal stacks and panel."""
    cohort = load_seed_cohort(fixture_path("xbrl/vintage_cohort.json"))
    assert len(cohort) == 16
    bac = [filing for filing in cohort if filing.firm == "BAC"]
    assert [(filing.fy, str(filing.accession)) for filing in bac] == [
        (2011, "0000070858-12-000155"),
        (2013, "0000070858-14-000012"),
        (2015, "0000070858-16-000137"),
        (2017, "0000070858-18-000009"),
        (2019, "0000070858-20-000011"),
        (2021, "0000070858-22-000062"),
        (2023, "0000070858-24-000122"),
    ]
    for filing in cohort:
        assert len(str(filing.accession)) == 20
        assert int(filing.cik) > 0
        assert filing.form in ("10-K", "20-F")
        assert 2011 <= filing.fy <= 2024


def test_load_sp100_cohort_from_fixture() -> None:
    """Verify loading 98 verified firms from the sp100 fixture."""
    cohort = load_seed_cohort(fixture_path("xbrl/taxonomy/sp100_cohort.json"))
    assert len(cohort) == 98
    firms = {f.firm for f in cohort}
    assert "AAPL" in firms
    assert "MSFT" in firms
    assert "JPM" in firms
    assert "NVDA" in firms
    for filing in cohort:
        assert len(str(filing.accession)) == 20
        assert int(filing.cik) > 0
        assert filing.form in ("10-K", "20-F")
