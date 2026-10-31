"""Filename constants for the engine/selection pipeline.

:no-path-tree:
"""

from __future__ import annotations

LOCATOR_FEATURES_FILE = "locator_features.parquet"
LIFECYCLE_FILE = "lifecycle.parquet"
POLICY_JSON_GLOB = "*.json"
OCCURRENCE_INDEPENDENT_FILE = "occurrence_independent.parquet"
LOCATOR_BANDS_FILE = "locator_bands.parquet"

__all__ = [
    "LOCATOR_FEATURES_FILE",
    "LIFECYCLE_FILE",
    "POLICY_JSON_GLOB",
    "OCCURRENCE_INDEPENDENT_FILE",
    "LOCATOR_BANDS_FILE",
]
