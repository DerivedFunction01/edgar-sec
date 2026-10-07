"""Filename constants for the engine/selection pipeline."""

from __future__ import annotations

OCCURRENCE_BASE_FILE = "occurrence_base.parquet"
OCCURRENCE_FEATURES_FILE = "occurrence_features.parquet"
LOCATOR_FEATURES_FILE = "locator_features.parquet"
LIFECYCLE_FILE = "lifecycle.parquet"
FEATURE_MANIFEST_FILE = "feature_snapshot.json"
POLICY_JSON_GLOB = "*.json"

__all__ = [
    "OCCURRENCE_BASE_FILE",
    "OCCURRENCE_FEATURES_FILE",
    "LOCATOR_FEATURES_FILE",
    "LIFECYCLE_FILE",
    "FEATURE_MANIFEST_FILE",
    "POLICY_JSON_GLOB",
]
