"""Corpus index writer: bundle records projected to index rows at ingest."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.apps.client.corpus_index import (
    index_bundle,
    index_bundles,
    index_facade,
    rows_from_records,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.infra.storage.corpus_index import CorpusIndex
from edgar_sec.tools.facade_battery import load_facade
from tests.support import bundle_dir, load_fixture

_FOLDERS = ("msft_2024_10k", "aapl_2024_10k", "jpm_2024_10k")


@pytest.fixture(scope="module")
def taxonomy() -> DomainTaxonomy:
    return load_domain_taxonomy()


def _identity(folder: str) -> tuple[str, str]:
    """(cik, accession) a seed folder's registry rows assign it."""
    sources = load_fixture("xbrl/seed/fixture_source_registry.json")["bundles"]
    accession = next(s["cohort_accession"] for s in sources if s["folder"] == folder)
    rows = load_fixture("xbrl/seed_cohort.json")
    cik = next(r["cik"] for r in rows if r["accession"] == accession)
    return cik, accession


def test_index_bundle_rows_match_facade_records(taxonomy: DomainTaxonomy) -> None:
    """Every bundle row equals the live facade's record projection."""
    index = CorpusIndex()
    for folder in _FOLDERS[:2]:
        cik, accession = _identity(folder)
        bundle = bundle_dir(folder)
        expected = rows_from_records(
            cik, accession, load_facade(bundle, taxonomy).facts.records
        )
        assert index_bundle(index, bundle, taxonomy, cik=cik) == len(expected)
        assert index.rows_for_filing(cik, accession) == expected
    index.close()


def test_index_facade_matches_index_bundle(taxonomy: DomainTaxonomy) -> None:
    """Indexing a built facade writes the same rows as indexing its bundle."""
    folder = _FOLDERS[0]
    cik, accession = _identity(folder)
    bundle = bundle_dir(folder)
    via_facade = CorpusIndex()
    index_facade(via_facade, load_facade(bundle, taxonomy), cik=cik)
    via_bundle = CorpusIndex()
    index_bundle(via_bundle, bundle, taxonomy, cik=cik)
    assert via_facade.rows_for_filing(cik, accession) == via_bundle.rows_for_filing(
        cik, accession
    )
    via_facade.close()
    via_bundle.close()


def test_index_bundles_parallel_matches_sequential(taxonomy: DomainTaxonomy) -> None:
    """Pool-built rows equal sequentially built rows, filing by filing."""
    bundles = tuple((bundle_dir(folder), _identity(folder)[0]) for folder in _FOLDERS)
    sequential = CorpusIndex()
    index_bundles(sequential, bundles, workers=1)
    parallel = CorpusIndex()
    index_bundles(parallel, bundles, workers=2)
    assert parallel.row_count() == sequential.row_count()
    for _bundle, cik in bundles:
        accession = _identity(_bundle.name)[1]
        assert parallel.rows_for_filing(cik, accession) == sequential.rows_for_filing(
            cik, accession
        )
    sequential.close()
    parallel.close()


def test_reindexing_a_bundle_replaces_its_rows(taxonomy: DomainTaxonomy) -> None:
    """A second ingest of one bundle leaves the row count unchanged."""
    folder = _FOLDERS[0]
    cik, _accession = _identity(folder)
    bundle = bundle_dir(folder)
    index = CorpusIndex()
    first = index_bundle(index, bundle, taxonomy, cik=cik)
    assert index_bundle(index, bundle, taxonomy, cik=cik) == first
    assert index.row_count() == first
    index.close()


def test_index_bundles_records_a_malformed_bundle_and_continues(
    taxonomy: DomainTaxonomy, tmp_path: Path
) -> None:
    """One malformed bundle fails its own filing; the batch completes."""
    broken = tmp_path / "broken_2024_10k"
    broken.mkdir()
    bundles = (
        (bundle_dir(_FOLDERS[0]), _identity(_FOLDERS[0])[0]),
        (broken, "0000000000"),
        (bundle_dir(_FOLDERS[1]), _identity(_FOLDERS[1])[0]),
    )
    index = CorpusIndex()
    result = index_bundles(index, bundles, workers=2)
    assert [failure.bundle for failure in result.failures] == ["broken_2024_10k"]
    assert result.failures[0].error.startswith("FileNotFoundError")
    assert result.rows_written > 0
    for folder in _FOLDERS[:2]:
        cik, accession = _identity(folder)
        expected = rows_from_records(
            cik, accession, load_facade(bundle_dir(folder), taxonomy).facts.records
        )
        assert index.rows_for_filing(cik, accession) == expected
    index.close()
