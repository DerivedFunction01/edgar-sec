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


def test_fact_set_dimensions_discovers_axes_with_families_and_members() -> None:
    """Discovery groups filed coordinates by axis, family, and member counts."""
    taxonomy = load_domain_taxonomy()
    amzn = XbrlFactSet(load_seed_facts("amzn_2023_10k"), taxonomy)
    by_axis = {coord.axis: coord for coord in amzn.dimensions()}
    timing = by_axis[
        "us-gaap:RevenueRemainingPerformanceObligationExpectedTimingOfSatisfactionStartDateAxis"
    ]
    assert timing.family == "HORIZON"
    assert timing.members == (("2024-01-01", 2),)
    segments = by_axis["us-gaap:StatementBusinessSegmentsAxis"]
    assert segments.family == "SEGMENT"
    assert ("amzn:AmazonWebServicesSegmentMember", 34) in segments.members

    msft = XbrlFactSet(load_seed_facts(_FOLDER), taxonomy)
    customers = {c.axis: c for c in msft.dimensions()}["srt:MajorCustomersAxis"]
    assert customers.family == "CUSTOMER"
    assert customers.members == (("msft:CommercialCustomersMember", 1),)


def test_fact_set_dimensions_empty_for_dimension_free_facts() -> None:
    """A set whose facts carry no dimensions discovers no coordinates."""
    taxonomy = load_domain_taxonomy()
    facts = tuple(f for f in load_seed_facts(_FOLDER) if not f.dimensions)
    assert XbrlFactSet(facts, taxonomy).dimensions() == ()


def test_facade_axes_delegates_to_fact_set_dimensions() -> None:
    """The facade's axes property is the fact set's discovery result."""
    facts = load_seed_facts("amzn_2023_10k")
    arcs = load_seed_calculation_arcs("amzn_2023_10k")
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs),
    )
    xbrl = Xbrl(bundle, load_domain_taxonomy())
    assert xbrl.axes == xbrl.facts.dimensions()
    assert any(coord.family == "HORIZON" for coord in xbrl.axes)


def test_builder_axis_family_filters_by_declared_family() -> None:
    """Facts dimensioned on a HORIZON axis are reachable by family name."""
    taxonomy = load_domain_taxonomy()
    amzn = XbrlFactSet(load_seed_facts("amzn_2023_10k"), taxonomy)
    horizon = amzn.query().axis_family("HORIZON").execute()
    assert len(horizon) > 0
    assert all(
        any(taxonomy.classify_axis(axis) == "HORIZON" for axis in f.dimensions)
        for f in horizon
    )
    rpo = [f for f in horizon if f.concept_qname.endswith("PerformanceObligation")]
    assert len(rpo) == 1
    assert rpo[0].value == 155_700_000_000.0


def test_builder_member_filters_by_member_on_any_axis() -> None:
    """The MSFT customer slice is the only fact on its member coordinate."""
    taxonomy = load_domain_taxonomy()
    msft = XbrlFactSet(load_seed_facts(_FOLDER), taxonomy)
    sliced = msft.query().member("msft:CommercialCustomersMember").execute()
    assert len(sliced) == 1
    assert sliced[0].value == 269_000_000_000.0


def test_builder_text_contains_searches_string_values_only() -> None:
    """Text search matches filed text blocks case-insensitively, never numerics."""
    taxonomy = load_domain_taxonomy()
    amzn = XbrlFactSet(load_seed_facts("amzn_2023_10k"), taxonomy)
    hits = (
        amzn.query()
        .concept("LeaseLiabilityReconciliationTableTextBlock")
        .text_contains("LEASE LIABILITIES")
        .execute()
    )
    assert len(hits) == 1
    assert isinstance(hits[0].value, str)

    msft = XbrlFactSet(load_seed_facts(_FOLDER), taxonomy)
    numeric_only = (
        msft.query()
        .concept("RevenueRemainingPerformanceObligation")
        .text_contains("275")
        .execute()
    )
    assert len(numeric_only) == 0


def test_builder_latest_period_keeps_principal_coordinate() -> None:
    """Latest period is the modal balance-sheet date, not a stray cover date."""
    taxonomy = load_domain_taxonomy()
    msft = XbrlFactSet(load_seed_facts(_FOLDER), taxonomy)
    latest = msft.query().latest_period().execute()
    assert len(latest) > 800
    assert all(
        f.instant_date == "2024-06-30"
        or (f.period_type == "duration" and f.end_date == "2024-06-30")
        for f in latest
    )
    assert any(f.concept_qname == "us-gaap:Assets" for f in latest)
    assert all(f.instant_date != "2024-07-25" for f in latest)


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
