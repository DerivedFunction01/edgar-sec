"""Display-fact records: tokenized once at set construction, consumed by filters."""

from edgar_sec.apps.client.facts import XbrlFactSet, build_display_records
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.storage.storage import (
    declarations_from_arrow_table,
    read_declarations_parquet,
)
from edgar_sec.engine.xbrl.taxonomy.item_types import item_type_local
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import load_seed_calculation_arcs, load_seed_facts
from tests.support import fixture_path

_FOLDER = "msft_2024_10k"


def _declarations():
    path = fixture_path(f"xbrl/seed/{_FOLDER}/declarations.parquet")
    return declarations_from_arrow_table(read_declarations_parquet(path))


def test_records_match_decomposer_on_every_seed_concept() -> None:
    """Tokenizer-service records agree with the decomposer, name-derived."""
    taxonomy = load_domain_taxonomy()
    facts = load_seed_facts(_FOLDER)
    records = build_display_records(facts, taxonomy)
    lex = taxonomy.token_lexicon
    assert lex is not None
    assert records
    for qname, record in records.items():
        atom, residuals, _, _ = decompose_concept(qname, lex)
        assert record.atom == atom
        assert record.residuals == residuals


def test_fact_set_records_computed_once_and_shared_with_builder() -> None:
    """Builder executions inherit the set's record objects, not recomputations."""
    taxonomy = load_domain_taxonomy()
    facts = load_seed_facts(_FOLDER)
    fact_set = XbrlFactSet(facts, taxonomy)
    assert fact_set.records
    subset = fact_set.query().concept("us-gaap:Assets").execute()
    assert subset.records["us-gaap:Assets"] is fact_set.records["us-gaap:Assets"]
    record = fact_set.record_for("us-gaap:Assets")
    assert record is not None
    assert record.atom.head == "H_ASSET"
    assert record.residual_mass == (0, 0)


def test_atom_filter_consumes_stored_records() -> None:
    """The .atom() filter's results equal a decomposer-driven reference scan."""
    taxonomy = load_domain_taxonomy()
    facts = load_seed_facts(_FOLDER)
    fact_set = XbrlFactSet(facts, taxonomy)
    lex = taxonomy.token_lexicon
    assert lex is not None
    expected = [
        f
        for f in facts
        if decompose_concept(f.concept_qname, lex)[0].head == "H_REVENUE"
    ]
    assert list(fact_set.query().atom("H_REVENUE").execute()) == expected


def test_item_type_and_text_coordinate_ride_the_record() -> None:
    """A declared text block carries its item type and the text coordinate."""
    facts = load_seed_facts(_FOLDER)
    arcs = load_seed_calculation_arcs(_FOLDER)
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs, declarations=_declarations()),
    )
    xbrl = Xbrl(bundle, load_domain_taxonomy())
    text_records = [
        record
        for record in xbrl.facts.records.values()
        if item_type_local(record.item_type) == "textBlockItemType"
    ]
    assert text_records
    assert "M_TEXT_NODE" in text_records[0].atom.modifiers
    monetary = xbrl.facts.records["us-gaap:Assets"]
    assert item_type_local(monetary.item_type) == "monetaryItemType"
    assert "M_TEXT_NODE" not in monetary.atom.modifiers


def test_facade_fact_set_and_financials_share_records() -> None:
    """The facade wires one record set into both the fact set and financials."""
    facts = load_seed_facts(_FOLDER)
    arcs = load_seed_calculation_arcs(_FOLDER)
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs, declarations=_declarations()),
    )
    xbrl = Xbrl(bundle, load_domain_taxonomy())
    assert (
        xbrl.financials._records["us-gaap:Assets"]
        is xbrl.facts.records["us-gaap:Assets"]
    )
    assert xbrl.financials.revenue_series == xbrl.financials._series("H_REVENUE")
