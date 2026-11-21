from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.breakdown import breakdown_concept
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def test_calculation_breakdown_applies_arc_weights() -> None:
    accession = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(accession, "us-gaap:Revenue", 12.0),
        XbrlFact(accession, "us-gaap:Costs", 5.0),
    ]
    arcs = [
        CalculationArc("us-gaap:Profit", "us-gaap:Revenue", 1.0),
        CalculationArc("us-gaap:Profit", "us-gaap:Costs", -1.0),
    ]

    result = breakdown_concept(
        EvidenceKnowledgeBase(load_domain_taxonomy()), "us-gaap:Profit", facts, arcs
    )

    assert [
        (component.identifier, component.weight) for component in result.components
    ] == [
        ("us-gaap:Revenue", 1.0),
        ("us-gaap:Costs", -1.0),
    ]


def test_breakdown_signed_discrepancy_keeps_residual_sign() -> None:
    """Verify signed_discrepancy is reported-minus-components, signed."""
    accession = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(accession, "us-gaap:Profit", 10.0),
        XbrlFact(accession, "us-gaap:Revenue", 12.0),
        XbrlFact(accession, "us-gaap:Costs", 5.0),
    ]
    arcs = [
        CalculationArc("us-gaap:Profit", "us-gaap:Revenue", 1.0),
        CalculationArc("us-gaap:Profit", "us-gaap:Costs", -1.0),
    ]

    result = breakdown_concept(
        EvidenceKnowledgeBase(load_domain_taxonomy()), "us-gaap:Profit", facts, arcs
    )

    assert result.discrepancy == 3.0
    assert result.signed_discrepancy == 3.0


def test_breakdown_period_key_scopes_facts_to_one_period() -> None:
    """Verify period_key selects one period; the default stays last-wins."""

    def fact(qname: str, value: float, instant: str) -> XbrlFact:
        return XbrlFact(
            AccessionNumber("0000950170-24-087843"),
            qname,
            value,
            unit="USD",
            period_type="instant",
            instant_date=instant,
        )

    facts = [
        fact("us-gaap:Profit", 10.0, "2023-12-31"),
        fact("us-gaap:Revenue", 12.0, "2023-12-31"),
        fact("us-gaap:Costs", 5.0, "2023-12-31"),
        fact("us-gaap:Profit", 20.0, "2024-12-31"),
        fact("us-gaap:Revenue", 25.0, "2024-12-31"),
        fact("us-gaap:Costs", 5.0, "2024-12-31"),
    ]
    arcs = [
        CalculationArc("us-gaap:Profit", "us-gaap:Revenue", 1.0),
        CalculationArc("us-gaap:Profit", "us-gaap:Costs", -1.0),
    ]
    kb = EvidenceKnowledgeBase(load_domain_taxonomy())

    scoped = breakdown_concept(
        kb,
        "us-gaap:Profit",
        facts,
        arcs,
        period_key=("instant", "2023-12-31", None, None),
    )
    assert scoped.total_value == 10.0
    assert scoped.signed_discrepancy == 3.0

    unscoped = breakdown_concept(kb, "us-gaap:Profit", facts, arcs)
    assert unscoped.total_value == 20.0
    assert unscoped.signed_discrepancy == 0.0
