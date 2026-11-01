"""Corpus search agreement: the seed index answers like the live facades.

Built once from the 49 seed bundles, the index is compared against
per-facade search over the same bundles, hit for hit, in ladder order.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.apps.client.comparison import DEFAULT_METRICS, screen_filings
from edgar_sec.apps.client.corpus_index import index_bundles, rows_from_records
from edgar_sec.apps.client.search import (
    CorpusSearchHit,
    FactSearchHit,
    search_index,
)
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.infra.storage.corpus_index import CorpusIndex
from tests.support import fixture_path, load_fixture

_TERMS = (
    "revenue",
    "net income",
    "gross profit",
    "total assets",
    "total liabilities",
    "operating cash flow",
    "cfo",
    "debt",
    "equity",
    "dividends",
    "revenue recognized",
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
)


def _seed_bundles() -> tuple[tuple[Path, str, str], ...]:
    """(bundle_dir, cik, accession) for the seed registry, in registry order."""
    registry = load_fixture("xbrl/seed_cohort.json")
    sources = load_fixture("xbrl/seed/fixture_source_registry.json")["bundles"]
    folder_by_accession = {s["cohort_accession"]: s["folder"] for s in sources}
    root = fixture_path("xbrl/seed")
    return tuple(
        (root / folder_by_accession[row["accession"]], row["cik"], row["accession"])
        for row in registry
    )


@pytest.fixture(scope="module")
def taxonomy() -> DomainTaxonomy:
    return load_domain_taxonomy()


@pytest.fixture(scope="module")
def seed_index(tmp_path_factory: pytest.TempPathFactory) -> CorpusIndex:
    """The seed corpus index, built per filing in a worker pool."""
    index = CorpusIndex(tmp_path_factory.mktemp("corpus") / "index.duckdb")
    index_bundles(index, [(d, cik) for d, cik, _ in _seed_bundles()])
    return index


@pytest.fixture(scope="module")
def seed_facades(taxonomy: DomainTaxonomy) -> dict[str, Xbrl]:
    """Live facades over the seed bundles, keyed by accession."""
    return {
        accession: Xbrl.from_bundle(bundle, taxonomy)
        for bundle, _cik, accession in _seed_bundles()
    }


def _live_key(hit: FactSearchHit) -> tuple:
    """The ranking fields a live hit carries, in comparison form."""
    return (
        hit.qname,
        hit.atom.to_dict(),
        hit.tier,
        hit.rule,
        hit.modifier_distance,
        hit.target_only,
        hit.hit_only,
        hit.swapped,
        hit.residual_mass,
    )


def _corpus_key(hit: CorpusSearchHit) -> tuple:
    """The ranking fields a corpus hit carries, in comparison form."""
    return (
        hit.qname,
        hit.atom.to_dict(),
        hit.tier,
        hit.rule,
        hit.modifier_distance,
        hit.target_only,
        hit.hit_only,
        hit.swapped,
        hit.residual_mass,
    )


def test_seed_index_rows_match_live_records(
    seed_index: CorpusIndex, seed_facades: dict[str, Xbrl]
) -> None:
    """Every filing's index rows equal its live facade's record projection."""
    assert seed_index.filing_count() == len(seed_facades) == 49
    cik_by_accession = {acc: cik for _d, cik, acc in _seed_bundles()}
    for accession, facade in seed_facades.items():
        expected = rows_from_records(
            cik_by_accession[accession], accession, facade.facts.records
        )
        assert seed_index.rows_for_filing(cik_by_accession[accession], accession) == (
            expected
        )


@pytest.mark.parametrize("term", _TERMS)
def test_corpus_search_agrees_with_live_search(
    term: str,
    seed_index: CorpusIndex,
    seed_facades: dict[str, Xbrl],
    taxonomy: DomainTaxonomy,
) -> None:
    """Per filing, corpus hits equal live hits: same set, same ladder order."""
    corpus = search_index(seed_index, term, taxonomy)
    by_accession: dict[str, list[CorpusSearchHit]] = {}
    for hit in corpus.hits:
        by_accession.setdefault(hit.accession, []).append(hit)
    for accession, facade in seed_facades.items():
        live = facade.search(term)
        assert corpus.target_atom == live.target_atom
        assert corpus.term_residuals == live.term_residuals
        assert corpus.partial == live.partial
        assert [_corpus_key(h) for h in by_accession.get(accession, [])] == [
            _live_key(h) for h in live.hits
        ]


def test_corpus_search_limit_agrees_with_live_limit(
    seed_index: CorpusIndex,
    seed_facades: dict[str, Xbrl],
    taxonomy: DomainTaxonomy,
) -> None:
    """A per-filing limit truncates corpus hits exactly as live search does."""
    corpus = search_index(seed_index, "revenue", taxonomy, limit=3)
    by_accession: dict[str, list[CorpusSearchHit]] = {}
    for hit in corpus.hits:
        by_accession.setdefault(hit.accession, []).append(hit)
    for accession, facade in seed_facades.items():
        live = facade.search("revenue", limit=3)
        assert [_corpus_key(h) for h in by_accession.get(accession, [])] == [
            _live_key(h) for h in live.hits
        ]


def test_screen_filings_covers_every_scalar_server(
    seed_index: CorpusIndex, seed_facades: dict[str, Xbrl]
) -> None:
    """Screened candidates include every filing the scalar rule serves.

    Screening may over-include; it must never drop a serving filing.
    """
    cik_by_accession = {acc: cik for _d, cik, acc in _seed_bundles()}
    screened = screen_filings(seed_index)
    assert set(screened) == {spec.key for spec in DEFAULT_METRICS}
    for spec in DEFAULT_METRICS:
        serving = {
            (cik_by_accession[accession], accession)
            for accession, facade in seed_facades.items()
            if facade.financials._scalar(
                spec.head, set(spec.modifiers), is_instant=spec.is_instant
            )
            is not None
        }
        assert serving <= set(screened[spec.key])
