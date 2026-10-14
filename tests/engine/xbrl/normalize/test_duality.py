"""Unit tests verifying Tag/Axis Duality normalization and frame subtraction."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.normalize.duality import (
    project_fact_duality,
    split_concept_tokens,
    unflatten_concept_name,
)
from edgar_sec.engine.xbrl.schema.models import XbrlFact


def test_split_concept_tokens() -> None:
    """Verify CamelCase tokenization of compound concept QNames."""
    assert split_concept_tokens("msft:WindowsCommercialRevenue") == (
        "Windows",
        "Commercial",
        "Revenue",
    )
    assert split_concept_tokens("aapl:PaymentsForStrategicSilicon") == (
        "Payments",
        "For",
        "Strategic",
        "Silicon",
    )


def test_unflatten_windows_commercial_revenue() -> None:
    """Verify unflattening WindowsCommercialRevenue into Revenues with customer slice and residual."""
    tax = load_domain_taxonomy()
    proj = unflatten_concept_name("msft:WindowsCommercialRevenue", tax)
    assert proj.canonical_measure == "Revenues"
    assert proj.origin == "FROM_NAME"
    assert proj.direction == 1.0
    assert proj.atom is not None
    assert proj.atom.head == "H_REVENUE"
    assert "Windows" in proj.residual_tokens

    families = {d.axis_family: d.member_qname for d in proj.dimensions}
    assert families["CUSTOMER"] == "CommercialMember"


def test_project_fact_duality_outflow_frame() -> None:
    """Verify direction negation and frame extraction for outflow frames."""
    tax = load_domain_taxonomy()
    acc = AccessionNumber("0000320193-24-000106")
    fact = XbrlFact(
        accession=acc,
        concept_qname="aapl:PaymentsForStrategicSiliconPrepayments",
        value=500.0,
        unit="USD",
        period_type="duration",
        start_date="2023-10-01",
        end_date="2024-09-30",
    )

    norm = project_fact_duality(fact, tax)
    assert norm.canonical_value == -500.0
    assert "Strategic" in norm.residual_tokens
    assert "Silicon" in norm.residual_tokens
