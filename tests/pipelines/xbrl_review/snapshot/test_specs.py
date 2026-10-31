"""Tests for XBRL snapshot relation specifications."""

from edgar_sec.pipelines.xbrl_review.snapshot.specs import (
    XBRL_CALCULATION_ARCS_SPEC,
    XBRL_HYPOTHESES_SPEC,
    XBRL_PRESENTATION_ARCS_SPEC,
    XBRL_QUARANTINE_SPEC,
    XBRL_RELATIONS,
    XBRL_RULE_TRACE_SPEC,
    XBRL_SOLVED_NODES_SPEC,
)


def test_xbrl_relations_tuple() -> None:
    """Verify XBRL_RELATIONS contains all six specs."""
    assert len(XBRL_RELATIONS) == 6
    names = {s.name for s in XBRL_RELATIONS}
    assert names == {
        "solved_nodes",
        "rule_trace",
        "quarantine",
        "hypotheses",
        "presentation_arcs",
        "calculation_arcs",
    }


def test_relation_specs_primary_keys() -> None:
    """Verify primary keys and entity keys on specs."""
    assert "accession" in XBRL_SOLVED_NODES_SPEC.primary_key
    assert "accession" in XBRL_RULE_TRACE_SPEC.primary_key
    assert "accession" in XBRL_QUARANTINE_SPEC.primary_key
    assert "rule_id" in XBRL_HYPOTHESES_SPEC.primary_key


def test_arc_specs_carry_full_row_primary_keys() -> None:
    """Verify arc keys keep repeated rollforward placements distinct."""
    assert XBRL_PRESENTATION_ARCS_SPEC.primary_key == (
        "accession",
        "parent_qname",
        "child_qname",
        "role_uri",
        "order",
    )
    assert XBRL_PRESENTATION_ARCS_SPEC.entity_key == "accession"
    assert XBRL_CALCULATION_ARCS_SPEC.primary_key == (
        "accession",
        "parent_qname",
        "child_qname",
        "role_uri",
        "weight",
        "order",
    )
    assert XBRL_CALCULATION_ARCS_SPEC.entity_key == "accession"


def test_quarantine_spec_keeps_pair_primary_key() -> None:
    """Verify quarantine v2 keeps the (accession, concept) primary key."""
    assert XBRL_QUARANTINE_SPEC.primary_key == ("accession", "concept_qname")
    assert XBRL_QUARANTINE_SPEC.schema.names == [
        "accession",
        "firm",
        "period",
        "concept_qname",
        "numeric_value",
        "reason",
        "fact_count",
    ]
