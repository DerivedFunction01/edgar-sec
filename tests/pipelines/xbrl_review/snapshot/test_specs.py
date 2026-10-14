"""Tests for XBRL snapshot relation specifications."""

from edgar_sec.pipelines.xbrl_review.snapshot.specs import (
    XBRL_HYPOTHESES_SPEC,
    XBRL_QUARANTINE_SPEC,
    XBRL_RELATIONS,
    XBRL_RULE_TRACE_SPEC,
    XBRL_SOLVED_NODES_SPEC,
)


def test_xbrl_relations_tuple() -> None:
    """Verify XBRL_RELATIONS contains all four core specs."""
    assert len(XBRL_RELATIONS) == 4
    names = {s.name for s in XBRL_RELATIONS}
    assert names == {"solved_nodes", "rule_trace", "quarantine", "hypotheses"}


def test_relation_specs_primary_keys() -> None:
    """Verify primary keys and entity keys on specs."""
    assert "accession" in XBRL_SOLVED_NODES_SPEC.primary_key
    assert "accession" in XBRL_RULE_TRACE_SPEC.primary_key
    assert "accession" in XBRL_QUARANTINE_SPEC.primary_key
    assert "rule_id" in XBRL_HYPOTHESES_SPEC.primary_key
