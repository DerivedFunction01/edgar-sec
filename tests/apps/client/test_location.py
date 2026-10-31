"""Filing-location provenance: document, role paths, parents, context."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.apps.client.location import build_location
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.storage.storage import presentation_arcs_from_arrow_table
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.apps.client.test_cohort_facts import (
    _ROLE,
    _SNAPSHOT_ACCESSION,
    _publish_fabricated_snapshot,
)
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
)
from tests.support import bundle_dir

_MSFT = "msft_2024_10k"
_REVENUE = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
_INCOME_ROLE = (
    "http://www.microsoft.com/20240630/taxonomy/role/Role_StatementINCOMESTATEMENTS"
)
_FY24_CONTEXT = "C_6dbdb3a2-9baf-41b4-922d-f59879124337"


def _facade(*, instance_document: str | None = None) -> Xbrl:
    table = pq.read_table(bundle_dir(_MSFT) / "presentation_arcs.parquet")
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=load_seed_facts(_MSFT),
        linkbases=LinkbaseBundle(
            calculation_arcs=load_seed_calculation_arcs(_MSFT),
            presentation_arcs=presentation_arcs_from_arrow_table(table),
        ),
        instance_document=instance_document,
    )
    return Xbrl(bundle, load_domain_taxonomy())


def test_msft_revenue_location() -> None:
    """Revenue traces to its roles, calc parent, and FY2024 context."""
    location = _facade().locate(_REVENUE, period="2024-06-30")
    assert location.document is None
    assert location.fidelity == "bundle"
    assert location.accession == "0000000000-24-000000"
    assert location.label is None

    placements = {p.title: p for p in location.placements}
    assert set(placements) == {
        "Income Statements",
        "Segment Revenue Detail",
        "Revenue Classified By Major Geographic Areas Detail",
        "Revenue Classified By Significant Product and Service Offerings Detail",
        (
            "Revenue Classified By Significant Product and Service "
            "Offerings Parenthetical Detail"
        ),
    }
    income = placements["Income Statements"]
    assert income.category == "statement"
    assert income.role_uri == _INCOME_ROLE
    assert income.path == (
        "us-gaap:IncomeStatementAbstract",
        "us-gaap:StatementTable",
        "us-gaap:StatementLineItems",
        _REVENUE,
    )

    assert len(location.calculation_parents) == 1
    parent = location.calculation_parents[0]
    assert parent.parent_qname == "us-gaap:GrossProfit"
    assert parent.weight == 1.0
    assert parent.role_uri == _INCOME_ROLE

    fact = location.fact
    assert fact is not None
    assert fact.value == 245_122_000_000.0
    assert fact.period_type == "duration"
    assert fact.start_date == "2023-07-01"
    assert fact.end_date == "2024-06-30"
    assert fact.instant_date is None
    assert fact.unit == "USD"
    assert fact.decimals == -6
    assert fact.context_id == _FY24_CONTEXT
    assert fact.dimensions == ()

    record = location.record
    assert record is not None
    assert record.atom.head == "H_REVENUE"
    assert record.atom.modifiers == frozenset(
        {"M_CONTRACT_CUSTOMER", "M_PRETAX", "M_TAX"}
    )
    assert record.residuals == ()
    assert record.tier == ""


def test_msft_revenue_location_names_instance_document() -> None:
    """A live-parse bundle names its instance document and fidelity."""
    location = _facade(instance_document="msft-20240630_htm.xml").locate(_REVENUE)
    assert location.document == "msft-20240630_htm.xml"
    assert location.fidelity == "instance"
    assert location.fact is not None
    assert location.fact.value == 245_122_000_000.0


def test_dimensioned_fact_dimensions_are_humanized() -> None:
    """Dimension coordinates display as axis and member names, not qnames."""
    facade = _facade()
    location = facade.locate(
        "msft:CreditLossAllowanceAndImpairmentOfInvestments", period="2024-06-30"
    )
    assert location.fact is not None
    assert location.fact.value == -23_000_000.0
    assert location.fact.dimensions == (("Financial Instrument", "Debt Securities"),)

    segment = next(
        fact
        for fact in facade.facts
        if fact.concept_qname == "us-gaap:OperatingIncomeLoss"
        and fact.dimensions.get("us-gaap:StatementBusinessSegmentsAxis")
        == "msft:ProductivityAndBusinessProcessesMember"
        and fact.end_date == "2024-06-30"
    )
    located = build_location(
        facade._kernel,
        facade._filing,
        facade.statements._catalog(),
        segment.concept_qname,
        fact=segment,
    )
    assert located.fact is not None
    assert located.fact.value == 40_540_000_000.0
    assert located.fact.dimensions == (
        ("Statement Business Segments", "Productivity And Business Processes"),
    )


def test_snapshot_facade_locates_at_reduced_fidelity(tmp_path: Path) -> None:
    """A snapshot facade answers with bundle identity and bare contexts."""
    snapshot_id = _publish_fabricated_snapshot(tmp_path, with_arcs=True)
    facade = Xbrl.from_snapshot(tmp_path, snapshot_id, _SNAPSHOT_ACCESSION)

    location = facade.locate("us-gaap:Assets", period="2024-09-28")
    assert location.fidelity == "snapshot"
    assert location.document is None
    assert location.accession == _SNAPSHOT_ACCESSION
    assert location.cik == "0000320193"
    assert location.fact is not None
    assert location.fact.value == 352_583_000_000.0
    assert location.fact.instant_date == "2024-09-28"
    assert location.fact.unit is None
    assert location.fact.decimals is None
    assert location.fact.dimensions == ()
    assert location.record is not None
    assert location.record.atom.head == "H_ASSET"

    child = facade.locate("us-gaap:AssetsCurrent")
    assert child.fact is None
    assert len(child.placements) == 1
    assert child.placements[0].role_uri == _ROLE
    assert child.placements[0].path == ("us-gaap:Assets", "us-gaap:AssetsCurrent")
    assert len(child.calculation_parents) == 1
    assert child.calculation_parents[0].parent_qname == "us-gaap:Assets"
    assert child.calculation_parents[0].weight == 1.0


def test_unknown_concept_location_is_empty() -> None:
    """A concept absent from the filing locates to an empty record."""
    location = _facade().locate("us-gaap:NoSuchConcept")
    assert location.placements == ()
    assert location.calculation_parents == ()
    assert location.fact is None
    assert location.record is None
    assert location.fidelity == "bundle"
