"""Declarative relational specifications for XBRL snapshot tables."""

from __future__ import annotations

from edgar_sec.infra.storage.dag.spec import RelationSpec
from edgar_sec.pipelines.xbrl_review.schemas import (
    CALCULATION_ARCS_SCHEMA,
    HYPOTHESES_SCHEMA,
    PRESENTATION_ARCS_SCHEMA,
    QUARANTINE_SCHEMA,
    RULE_TRACE_SCHEMA,
    SOLVED_NODES_SCHEMA,
)

XBRL_SOLVED_NODES_SPEC = RelationSpec(
    name="solved_nodes",
    schema=SOLVED_NODES_SCHEMA,
    primary_key=("accession", "concept_qname", "period"),
    merge_strategy="upsert",
    sort_order=("accession", "concept_qname"),
    entity_key="accession",
)

XBRL_RULE_TRACE_SPEC = RelationSpec(
    name="rule_trace",
    schema=RULE_TRACE_SCHEMA,
    primary_key=("accession", "rule_id"),
    merge_strategy="upsert",
    sort_order=("accession", "rule_id"),
    entity_key="accession",
)

XBRL_QUARANTINE_SPEC = RelationSpec(
    name="quarantine",
    schema=QUARANTINE_SCHEMA,
    primary_key=("accession", "concept_qname"),
    merge_strategy="upsert",
    sort_order=("accession", "concept_qname"),
    entity_key="accession",
)

XBRL_HYPOTHESES_SPEC = RelationSpec(
    name="hypotheses",
    schema=HYPOTHESES_SCHEMA,
    primary_key=("rule_id",),
    merge_strategy="upsert",
    sort_order=("rule_id",),
)

# Arc keys are the full arc row: a rollforward places the same
# (parent, child, role) at several orders, and each placement counts.
XBRL_PRESENTATION_ARCS_SPEC = RelationSpec(
    name="presentation_arcs",
    schema=PRESENTATION_ARCS_SCHEMA,
    primary_key=("accession", "parent_qname", "child_qname", "role_uri", "order"),
    merge_strategy="upsert",
    sort_order=("accession", "parent_qname", "child_qname"),
    entity_key="accession",
)

XBRL_CALCULATION_ARCS_SPEC = RelationSpec(
    name="calculation_arcs",
    schema=CALCULATION_ARCS_SCHEMA,
    primary_key=(
        "accession",
        "parent_qname",
        "child_qname",
        "role_uri",
        "weight",
        "order",
    ),
    merge_strategy="upsert",
    sort_order=("accession", "parent_qname", "child_qname"),
    entity_key="accession",
)

XBRL_RELATIONS = (
    XBRL_SOLVED_NODES_SPEC,
    XBRL_RULE_TRACE_SPEC,
    XBRL_QUARANTINE_SPEC,
    XBRL_HYPOTHESES_SPEC,
    XBRL_PRESENTATION_ARCS_SPEC,
    XBRL_CALCULATION_ARCS_SPEC,
)

__all__ = [
    "XBRL_CALCULATION_ARCS_SPEC",
    "XBRL_HYPOTHESES_SPEC",
    "XBRL_PRESENTATION_ARCS_SPEC",
    "XBRL_QUARANTINE_SPEC",
    "XBRL_RELATIONS",
    "XBRL_RULE_TRACE_SPEC",
    "XBRL_SOLVED_NODES_SPEC",
]
