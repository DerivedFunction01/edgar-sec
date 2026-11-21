"""Tests for XBRL review pipeline Parquet dataset schemas."""

import pyarrow as pa

from edgar_sec.pipelines.xbrl_review.schemas import (
    CALCULATION_ARCS_SCHEMA,
    CALCULATION_ARCS_SCHEMA_VERSION,
    HYPOTHESES_SCHEMA,
    HYPOTHESES_SCHEMA_VERSION,
    PRESENTATION_ARCS_SCHEMA,
    PRESENTATION_ARCS_SCHEMA_VERSION,
    QUARANTINE_SCHEMA,
    QUARANTINE_SCHEMA_VERSION,
    RULE_TRACE_SCHEMA,
    SOLVED_NODES_SCHEMA,
    WORK_ORDER_SCHEMA,
)


def test_solved_nodes_schema() -> None:
    """Verify solved nodes Arrow schema fields and types."""
    assert isinstance(SOLVED_NODES_SCHEMA, pa.Schema)
    assert "accession" in SOLVED_NODES_SCHEMA.names
    assert "concept_qname" in SOLVED_NODES_SCHEMA.names
    assert "derived_value" in SOLVED_NODES_SCHEMA.names


def test_other_xbrl_schemas() -> None:
    """Verify quarantine, hypotheses, and work order schemas."""
    assert isinstance(RULE_TRACE_SCHEMA, pa.Schema)
    assert isinstance(QUARANTINE_SCHEMA, pa.Schema)
    assert isinstance(HYPOTHESES_SCHEMA, pa.Schema)
    assert isinstance(WORK_ORDER_SCHEMA, pa.Schema)


def test_quarantine_schema_v2_inventory() -> None:
    """Verify quarantine v2 drops vestigial fields for reason and count."""
    assert QUARANTINE_SCHEMA_VERSION == 2
    assert QUARANTINE_SCHEMA.names == [
        "accession",
        "firm",
        "period",
        "concept_qname",
        "numeric_value",
        "reason",
        "fact_count",
    ]
    assert QUARANTINE_SCHEMA.field("reason").type == pa.string()
    assert QUARANTINE_SCHEMA.field("fact_count").type == pa.int64()
    assert QUARANTINE_SCHEMA.field("numeric_value").type == pa.float64()


def test_arc_schemas_carry_accession_and_arc_fields() -> None:
    """Verify the arc schemas mirror the bundle arc rows plus accession."""
    assert PRESENTATION_ARCS_SCHEMA_VERSION == 1
    assert PRESENTATION_ARCS_SCHEMA.names == [
        "accession",
        "parent_qname",
        "child_qname",
        "order",
        "role_uri",
    ]
    assert CALCULATION_ARCS_SCHEMA_VERSION == 1
    assert CALCULATION_ARCS_SCHEMA.names == [
        "accession",
        "parent_qname",
        "child_qname",
        "weight",
        "order",
        "role_uri",
    ]
    assert CALCULATION_ARCS_SCHEMA.field("weight").type == pa.float64()


def test_hypotheses_schema_v2_carries_period() -> None:
    """Verify hypotheses v2 adds the period column and nothing else."""
    assert HYPOTHESES_SCHEMA_VERSION == 2
    assert HYPOTHESES_SCHEMA.names == [
        "rule_id",
        "hypothesis_type",
        "target_concept",
        "source_concept",
        "algebraic_weight",
        "firm",
        "sector",
        "period",
        "evidence_value",
    ]
