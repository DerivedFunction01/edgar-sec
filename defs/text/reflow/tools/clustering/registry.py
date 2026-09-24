"""Tools re-export of the production Feature Registry."""

from __future__ import annotations

from defs.text.reflow.registry import (
    FEATURE_REGISTRY,
    FeatureSpec,
)
from defs.text.reflow.tools.clustering.experimental_registry import (
    EXPERIMENTAL_REGISTRY,
    get_experimental_features,
    get_production_features,
    override_threshold,
    register_experimental,
    reset_to_production,
)

__all__ = [
    "EXPERIMENTAL_REGISTRY",
    "FEATURE_REGISTRY",
    "FeatureSpec",
    "get_experimental_features",
    "get_production_features",
    "override_threshold",
    "register_experimental",
    "reset_to_production",
]
