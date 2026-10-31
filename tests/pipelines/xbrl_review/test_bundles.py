"""Tests for XBRL review corpus-bundle resolution and loading."""

import json
from pathlib import Path

import pytest

from edgar_sec.engine.xbrl.discovery.cohort import (
    canonical_probe_cohort_path,
    canonical_seed_cohort_path,
    canonical_sp100_cohort_path,
    canonical_vintage_cohort_path,
    load_canonical_union_cohort,
)
from edgar_sec.pipelines.xbrl_review.bundles import (
    BundleNotFoundError,
    bundle_dir_for,
    bundle_root,
    corpus_registry_path,
    load_filing,
    missing_bundles,
    registry_filings,
)


def test_registry_filings_cover_canonical_registry() -> None:
    """Verify the canonical seed registry loads in full."""
    filings = registry_filings()
    assert len(filings) == 49
    assert len({str(f.accession) for f in filings}) == 49


def test_registry_filings_with_vintage_registry_path() -> None:
    """Verify a registry path loads that dataset's registry instead."""
    filings = registry_filings(registry_path=canonical_vintage_cohort_path())
    assert len(filings) == 16
    assert {f.firm for f in filings} == {"BAC", "MSFT", "AAPL", "SHEL", "BP", "NVS"}


def test_registry_filings_with_sp100_registry_path() -> None:
    """Verify a registry path loads the SP100 scale corpus instead."""
    filings = registry_filings(registry_path=canonical_sp100_cohort_path())
    assert len(filings) == 60
    assert len({f.firm for f in filings}) == 60
    assert {"MA", "ARM", "AZN", "BABA"} <= {f.firm for f in filings}


def test_every_registry_accession_has_a_bundle() -> None:
    """Verify no registry filing is missing its corpus bundle."""
    accessions = [str(f.accession) for f in load_canonical_union_cohort()]
    assert missing_bundles(accessions) == []


def test_corpus_registry_path_recognizes_only_corpus_registries(
    tmp_path: Path,
) -> None:
    """Verify a source ref selects a corpus only with its source registry."""
    assert corpus_registry_path(str(canonical_seed_cohort_path())) == (
        canonical_seed_cohort_path()
    )
    assert corpus_registry_path(str(canonical_vintage_cohort_path())) == (
        canonical_vintage_cohort_path()
    )
    assert corpus_registry_path(str(canonical_sp100_cohort_path())) == (
        canonical_sp100_cohort_path()
    )
    assert corpus_registry_path(str(canonical_probe_cohort_path())) == (
        canonical_probe_cohort_path()
    )
    assert corpus_registry_path(None) is None
    plain = tmp_path / "dataset.json"
    plain.write_text("[]", encoding="utf-8")
    assert corpus_registry_path(str(plain)) is None


def test_bundle_dir_for_vintage_accession_resolves_vintage_root() -> None:
    """Verify BAC 2011 resolves from the vintage corpus (cross-corpus pair)."""
    bundle_dir = bundle_dir_for("0000070858-12-000155")
    assert bundle_dir.parent.name == "vintage"
    assert bundle_dir.name == "bac_2011_10k"


def test_bundle_dir_for_restricted_to_wrong_corpus_refuses() -> None:
    """Verify a registry path restricts resolution to its own corpus."""
    with pytest.raises(BundleNotFoundError):
        bundle_dir_for(
            "0000070858-12-000155", registry_path=canonical_seed_cohort_path()
        )


def test_bundle_dir_for_sp100_accession_resolves_sp100_root() -> None:
    """Verify MA 2024 resolves from the SP100 corpus root."""
    bundle_dir = bundle_dir_for("0001141391-25-000011")
    assert bundle_dir.parent.name == "sp100"
    assert bundle_dir.name == "ma_2024_10k"


def test_bundle_dir_for_sp100_restricted_to_seed_refuses() -> None:
    """Verify an SP100 accession refuses under the seed registry alone."""
    with pytest.raises(BundleNotFoundError):
        bundle_dir_for(
            "0001141391-25-000011", registry_path=canonical_seed_cohort_path()
        )


def test_bundle_dir_for_unknown_accession_refuses() -> None:
    """Verify an unregistered accession is a refusal, not an empty bundle."""
    with pytest.raises(BundleNotFoundError):
        bundle_dir_for("0000000000-25-000001")


def test_load_filing_reads_vintage_bundle() -> None:
    """Verify a vintage filing loads through the same bundle path."""
    bac_2011 = next(
        f
        for f in registry_filings(registry_path=canonical_vintage_cohort_path())
        if f.fy == 2011
    )
    loaded = load_filing(bac_2011)
    assert len(loaded.facts) > 1000
    assert loaded.bundle_dir.parent.name == "vintage"


def test_registry_filings_with_probe_registry_path() -> None:
    """Verify a registry path loads the 10-Q/8-K probe corpus instead."""
    filings = registry_filings(registry_path=canonical_probe_cohort_path())
    assert len(filings) == 7
    assert len({str(f.accession) for f in filings}) == 7
    forms = [f.form for f in filings]
    assert forms.count("10-Q") == 4
    assert forms.count("8-K") == 3
    assert {f.firm for f in filings} == {"MSFT", "AAPL", "JPM", "CAT", "AMZN"}


def test_probe_registry_source_folder_bijection() -> None:
    """Verify probe registry, source registry, and folders correspond 1:1."""
    registry_path = canonical_probe_cohort_path()
    filings = registry_filings(registry_path=registry_path)
    root = bundle_root(registry_path)
    payload = json.loads(
        (root / "fixture_source_registry.json").read_text(encoding="utf-8")
    )
    sources = payload["bundles"]
    assert {str(f.accession) for f in filings} == {
        s["cohort_accession"] for s in sources
    }
    assert {s["folder"] for s in sources} == {
        p.name for p in root.iterdir() if p.is_dir()
    }
    for source in sources:
        assert source["source_accession"] == source["cohort_accession"]
        assert source["source_matches_cohort"] is True
        assert source["provenance_status"] == "VERIFIED"
        assert (root / source["folder"] / "facts.parquet").is_file()


def test_bundle_dir_for_probe_accession_resolves_probe_root() -> None:
    """Verify a probe 10-Q accession resolves from the probe corpus root."""
    bundle_dir = bundle_dir_for("0001193125-26-436133")
    assert bundle_dir.parent.name == "probe"
    assert bundle_dir.name == "msft_2026_10q"


def test_bundle_dir_for_probe_restricted_to_seed_refuses() -> None:
    """Verify a probe accession refuses under the seed registry alone."""
    with pytest.raises(BundleNotFoundError):
        bundle_dir_for(
            "0001193125-26-436133", registry_path=canonical_seed_cohort_path()
        )


def test_load_filing_reads_probe_bundle() -> None:
    """Verify a probe 10-Q loads through the same bundle path."""
    msft_q = next(
        f
        for f in registry_filings(registry_path=canonical_probe_cohort_path())
        if f.firm == "MSFT" and f.form == "10-Q"
    )
    loaded = load_filing(msft_q, registry_path=canonical_probe_cohort_path())
    assert len(loaded.facts) > 1000
    assert loaded.bundle_dir.parent.name == "probe"


def test_load_filing_reads_bundle_artefacts() -> None:
    """Verify one filing loads facts, arcs, and declarations."""
    mcd = next(f for f in registry_filings() if f.firm == "MCD")
    loaded = load_filing(mcd)
    assert len(loaded.facts) > 1000
    assert len(loaded.calc_arcs) > 100
    assert len(loaded.pres_arcs) > 100
    assert {arc.parent_qname for arc in loaded.pres_arcs}
    assert "us-gaap:CashAndCashEquivalentsAtCarryingValue" in loaded.declarations
    assert loaded.cohort_entry.accession == str(mcd.accession)
    assert loaded.cohort_entry.facts_path.is_file()
