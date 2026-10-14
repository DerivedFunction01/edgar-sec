"""Tests for XBRL review pipeline Parquet dataset schemas."""

import pyarrow as pa

from edgar_sec.pipelines.xbrl_review.schemas import (
    HYPOTHESES_SCHEMA,
    QUARANTINE_SCHEMA,
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
