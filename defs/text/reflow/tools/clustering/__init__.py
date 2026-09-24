"""Reflow feature clustering, analysis, and zero-corruption rule suite."""

from __future__ import annotations

from .audit import AuditSummary, run_zero_corruption_audit
from .context import BlockContext
from .dataset import (
    COHORT_CANDIDATES,
    COHORT_CLEAN_PROSE,
    COHORT_CLEAN_TABLES,
    COHORT_EDGE_CASE_TABLES,
    DatasetBlock,
    extract_feature_matrix,
    load_dataset_from_jsonl,
)
from .registry import FEATURE_REGISTRY, FeatureSpec
from .rules import (
    FEATURE_GROUPS,
    FeatureThreshold,
    GroupQuota,
    Rule,
    RuleEngine,
    SynergyRule,
)
from .unsupervised import (
    ClusteringAnalysisResult,
    run_unsupervised_analysis,
)

__all__ = [
    "COHORT_CANDIDATES",
    "COHORT_CLEAN_PROSE",
    "COHORT_CLEAN_TABLES",
    "COHORT_EDGE_CASE_TABLES",
    "FEATURE_GROUPS",
    "FEATURE_REGISTRY",
    "AuditSummary",
    "BlockContext",
    "ClusteringAnalysisResult",
    "DatasetBlock",
    "FeatureSpec",
    "FeatureThreshold",
    "GroupQuota",
    "Rule",
    "RuleEngine",
    "SynergyRule",
    "extract_feature_matrix",
    "load_dataset_from_jsonl",
    "run_unsupervised_analysis",
    "run_zero_corruption_audit",
]
