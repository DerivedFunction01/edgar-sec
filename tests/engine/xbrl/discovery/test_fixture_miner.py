"""Tests for mining fact concept token n-grams and taxonomy coverage."""

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.discovery.fixture_miner import (
    evaluate_taxonomy_fact_coverage,
    mine_fact_token_ngrams,
    tokenize_fact_concept,
)
from tests.support import fixture_path


def test_tokenize_fact_concept() -> None:
    """Verify camel-case and extension fact concept tokenization."""
    qname = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    tokens = tokenize_fact_concept(qname)
    assert tokens == [
        "revenue",
        "from",
        "contract",
        "with",
        "customer",
        "excluding",
        "assessed",
        "tax",
    ]

    ext_qname = "jpm:PreProvisionProfit"
    assert tokenize_fact_concept(ext_qname) == ["pre", "provision", "profit"]


def test_mine_fact_token_ngrams() -> None:
    """Verify fact concept n-gram extraction across real grounded filing."""
    facts_p = fixture_path("xbrl/seed/msft_2024_10k/facts.parquet")
    table = pq.read_table(facts_p)

    ngrams = mine_fact_token_ngrams(table, n_range=(2, 3))
    assert len(ngrams) > 50
    assert ("contract", "customer") in ngrams or ("operating", "lease") in ngrams


def test_evaluate_taxonomy_fact_coverage() -> None:
    """Verify fact taxonomy coverage metrics and isolation of OOV n-grams."""
    facts_p = fixture_path("xbrl/seed/msft_2024_10k/facts.parquet")
    table = pq.read_table(facts_p)

    report = evaluate_taxonomy_fact_coverage(table)
    assert report.total_facts > 1000
    assert report.unique_concepts > 100
    assert 0.0 < report.token_coverage_ratio <= 1.0
    assert len(report.top_oov_ngrams) > 0
