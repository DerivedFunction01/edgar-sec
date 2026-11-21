"""Tests for the K1 census filing accounting."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.tools.xbrl_eval.xbrl_k1_census import disposition_for, filing_k1_blocks

ACC = AccessionNumber("0000000000-26-000001")


def _fact(qname, value, *, dims=None):
    """One synthetic instant fact, dimensioned when dims are given."""
    return XbrlFact(
        accession=ACC,
        concept_qname=qname,
        value=value,
        period_type="instant",
        instant_date="2026-03-31",
        dimensions=dims or {},
    )


def test_disposition_priority_order() -> None:
    """Per-share outranks schedule, which outranks served and calc evidence."""
    assert disposition_for("us-gaap:Eps", "us-gaap", True, True, True) == "per_share"
    assert disposition_for("oef:AccmVal", "oef", True, True, False) == "schedule"
    assert disposition_for("us-gaap:Rev", "us-gaap", True, True, False) == (
        "breakdown_served"
    )
    assert disposition_for("us-gaap:Sub", "us-gaap", True, False, False) == (
        "calc_component"
    )
    assert disposition_for("us-gaap:Lone", "us-gaap", False, False, False) == "orphan"


def test_filing_k1_blocks_partition_dimensioned_only_mass() -> None:
    """Only dimensioned concepts with no undimensioned numeric twin count."""
    facts = (
        _fact("us-gaap:Revenue", 100.0),
        _fact("us-gaap:Revenue", 60.0, dims={"Seg": "A"}),
        _fact("us-gaap:Revenue", 40.0, dims={"Seg": "B"}),
        _fact("us-gaap:DetailOnly", 5.0, dims={"Seg": "A"}),
        _fact("us-gaap:DetailOnly", 7.0, dims={"Seg": "B"}),
        _fact("oef:Holding", 3.0, dims={"Inv": "X"}),
        _fact("us-gaap:TextDim", "n/a", dims={"Seg": "A"}),
    )
    arcs = (CalculationArc("us-gaap:Parent", "us-gaap:DetailOnly", 1.0, 1),)
    blocks = filing_k1_blocks(facts, arcs, {"us-gaap:Revenue"}, lambda q: False)
    us = blocks["us-gaap"]
    assert us["k1_facts"] == 2
    assert us["calc_component"] == 2
    assert us["in_calc_arcs"] == 2
    assert blocks["oef"]["schedule"] == 1
    assert blocks["oef"]["no_calc_role"] == 1


def test_filing_k1_blocks_empty_when_every_concept_is_served() -> None:
    """A filing whose dimensioned concepts all have undimensioned twins has no K1."""
    facts = (
        _fact("us-gaap:Revenue", 100.0),
        _fact("us-gaap:Revenue", 60.0, dims={"Seg": "A"}),
    )
    assert filing_k1_blocks(facts, (), set(), lambda q: False) == {}
