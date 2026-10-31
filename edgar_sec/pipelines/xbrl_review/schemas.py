"""Parquet dataset schemas and version constants for XBRL review pipeline."""

from __future__ import annotations

import pyarrow as pa

SOLVED_NODES_SCHEMA_VERSION = 1
RULE_TRACE_SCHEMA_VERSION = 1
QUARANTINE_SCHEMA_VERSION = 2
HYPOTHESES_SCHEMA_VERSION = 2
WORK_ORDER_SCHEMA_VERSION = 1
PRESENTATION_ARCS_SCHEMA_VERSION = 1
CALCULATION_ARCS_SCHEMA_VERSION = 1

SOLVED_NODES_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("concept_qname", pa.string()),
        ("period", pa.string()),
        ("firm", pa.string()),
        ("cik", pa.int64()),
        ("prime_head", pa.string()),
        ("modifiers_json", pa.string()),
        ("resolution_tier", pa.string()),
        ("reported_value", pa.float64()),
        ("derived_value", pa.float64()),
        ("derivation_path", pa.string()),
        ("latency_ms", pa.float64()),
    ]
)

RULE_TRACE_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("rule_id", pa.string()),
        ("status", pa.string()),
        ("lhs_value", pa.float64()),
        ("rhs_value", pa.float64()),
        ("discrepancy", pa.float64()),
        ("evidence_nodes", pa.string()),
    ]
)

# Quarantine v2: one row per (accession, concept_qname) pair; reason is the
# engine vocabulary (QUARANTINE_REASONS) and fact_count the unconsumed count.
QUARANTINE_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("firm", pa.string()),
        ("period", pa.string()),
        ("concept_qname", pa.string()),
        ("numeric_value", pa.float64()),
        ("reason", pa.string()),
        ("fact_count", pa.int64()),
    ]
)

HYPOTHESES_SCHEMA = pa.schema(
    [
        ("rule_id", pa.string()),
        ("hypothesis_type", pa.string()),
        ("target_concept", pa.string()),
        ("source_concept", pa.string()),
        ("algebraic_weight", pa.float64()),
        ("firm", pa.string()),
        ("sector", pa.string()),
        ("period", pa.string()),
        ("evidence_value", pa.float64()),
    ]
)

PRESENTATION_ARCS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("parent_qname", pa.string()),
        ("child_qname", pa.string()),
        ("order", pa.float64()),
        ("role_uri", pa.string()),
    ]
)

CALCULATION_ARCS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("parent_qname", pa.string()),
        ("child_qname", pa.string()),
        ("weight", pa.float64()),
        ("order", pa.float64()),
        ("role_uri", pa.string()),
    ]
)

WORK_ORDER_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("cik", pa.int64()),
        ("report_date", pa.string()),
    ]
)

__all__ = [
    "CALCULATION_ARCS_SCHEMA",
    "CALCULATION_ARCS_SCHEMA_VERSION",
    "HYPOTHESES_SCHEMA",
    "HYPOTHESES_SCHEMA_VERSION",
    "PRESENTATION_ARCS_SCHEMA",
    "PRESENTATION_ARCS_SCHEMA_VERSION",
    "QUARANTINE_SCHEMA",
    "QUARANTINE_SCHEMA_VERSION",
    "RULE_TRACE_SCHEMA",
    "RULE_TRACE_SCHEMA_VERSION",
    "SOLVED_NODES_SCHEMA",
    "SOLVED_NODES_SCHEMA_VERSION",
    "WORK_ORDER_SCHEMA",
    "WORK_ORDER_SCHEMA_VERSION",
]
