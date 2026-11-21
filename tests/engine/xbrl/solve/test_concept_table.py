"""Tests for the per-process concept-to-atom table builder."""

from __future__ import annotations

import pyarrow.parquet as pq
import pytest

from edgar_sec.engine.xbrl.normalize.decomposer import residual_counts
from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
from edgar_sec.engine.xbrl.solve.concept_table import (
    build_cohort_table,
    build_concept_table,
    cohort_qnames,
)
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.taxonomy.domain import (
    DomainTaxonomy,
    load_domain_taxonomy,
)
from tests.engine.xbrl.solve.conftest import load_seed_cohort


@pytest.fixture(scope="module")
def taxonomy() -> DomainTaxonomy:
    return load_domain_taxonomy()


def test_table_records_match_direct_tokenizer(taxonomy: DomainTaxonomy) -> None:
    """Table rows equal direct tokenizer runs, residual counts included."""
    qnames = (
        "us-gaap:AccountsPayable",
        "us-gaap:AccountsPayableCurrent",
        "us-gaap:Revenues",
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
    )
    table = build_concept_table(taxonomy, qnames)
    direct = ConceptTokenizer(taxonomy)
    assert len(table) == len(qnames)
    for qname in qnames:
        record = table.record(qname)
        expected = direct.tokenize(qname, table.declaration(qname))
        assert record.atom == expected.atom
        assert record.presumed_atom == expected.presumed_atom
        assert record.residuals == expected.residuals
        assert (record.residual_intent, record.residual_total) == residual_counts(
            expected.residuals
        )
        assert record.derived_horizon == expected.derived_horizon


def test_table_carries_item_type_and_text_coordinate(
    taxonomy: DomainTaxonomy,
) -> None:
    """Item types ride the record; a text type asserts the text coordinate."""
    table = build_concept_table(
        taxonomy,
        (
            "us-gaap:AccountsPayableCurrent",
            "us-gaap:SignificantAccountingPoliciesTextBlock",
        ),
    )
    monetary = table.record("us-gaap:AccountsPayableCurrent")
    assert monetary.item_type == "xbrli:monetaryItemType"
    text = table.record("us-gaap:SignificantAccountingPoliciesTextBlock")
    assert text.item_type == "dtr-types:textBlockItemType"
    assert "M_TEXT_NODE" in text.atom.modifiers
    assert "M_TEXT_NODE" not in monetary.atom.modifiers


def test_table_presumed_modifier_names_the_default(
    taxonomy: DomainTaxonomy,
) -> None:
    """Bare payables presumes current; the record names the added modifier."""
    table = build_concept_table(taxonomy, ("us-gaap:AccountsPayable",))
    record = table.record("us-gaap:AccountsPayable")
    assert record.presumed_modifier == "M_CURRENT"
    assert record.presumed_atom.modifiers - record.atom.modifiers == {"M_CURRENT"}
    assert record.presumed_signature.startswith('{"head":"H_LIABILITY"')


def test_extension_declaration_wins_over_standard_table(
    taxonomy: DomainTaxonomy,
) -> None:
    """An extension declaration's item type replaces the standard entry."""
    declaration = ConceptDeclaration(
        concept_qname="us-gaap:AccountsPayableCurrent",
        name="AccountsPayableCurrent",
        item_type="xbrli:stringItemType",
    )
    table = build_concept_table(
        taxonomy,
        ("us-gaap:AccountsPayableCurrent",),
        declarations=(declaration,),
    )
    record = table.record("us-gaap:AccountsPayableCurrent")
    assert record.item_type == "xbrli:stringItemType"
    assert "M_TEXT_NODE" in record.atom.modifiers


def test_cohort_qnames_reads_bundle_parquets(taxonomy: DomainTaxonomy) -> None:
    """The cohort's distinct qnames come from its bundles' facts."""
    entries = load_seed_cohort()[:3]
    expected = set()
    for entry in entries:
        table = pq.read_table(entry.facts_path, columns=["concept_qname"])
        expected.update(table.column(0).to_pylist())
    assert cohort_qnames(entries) == tuple(sorted(expected))


def test_full_cohort_table_population(taxonomy: DomainTaxonomy) -> None:
    """A full-cohort build covers every distinct reported qname once."""
    entries = load_seed_cohort()
    expected = set()
    for entry in entries:
        table = pq.read_table(entry.facts_path, columns=["concept_qname"])
        expected.update(table.column(0).to_pylist())
    table = build_cohort_table(taxonomy, entries)
    assert len(table) == len(expected)
    assert set(table.records) == expected
    assert len(table.distinct_atoms) == len(
        {record.atom for record in table.records.values()}
    )
    direct = ConceptTokenizer(taxonomy)
    for qname in sorted(expected)[:: max(1, len(expected) // 25)]:
        record = table.record(qname)
        assert record.atom == direct.tokenize(qname, table.declaration(qname)).atom
