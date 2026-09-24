"""Experimental & Analysis Feature Registry.

Separates research, feature experimentation, and threshold sweeps from the
locked-down production registry in ``defs.text.reflow.registry``.

Experimental features can be added, tested, and calibrated here without
modifying production code until they pass the zero-corruption audit gate.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import copy
from typing import Any

from defs.text.reflow.registry import FEATURE_REGISTRY, FeatureSpec

# Mutable experimental feature registry initialized with copies of production specs
EXPERIMENTAL_REGISTRY: dict[str, FeatureSpec] = {
    name: copy(spec) for name, spec in FEATURE_REGISTRY.items()
}


def register_experimental(
    name: str,
    scalar_type: type,
    description: str,
    default_predicate: Callable[[Any], bool],
    optimal_threshold: float | None = None,
    hypothesis_ref: str | None = None,
    default_group: str | None = None,
) -> FeatureSpec:
    """Register a new speculative feature in the experimental registry."""
    spec = FeatureSpec(
        name=name,
        scalar_type=scalar_type,
        description=description,
        default_predicate=default_predicate,
        optimal_threshold=optimal_threshold,
        hypothesis_ref=hypothesis_ref,
        default_group=default_group,
    )
    EXPERIMENTAL_REGISTRY[name] = spec
    return spec


def override_threshold(
    name: str,
    new_threshold: float,
    predicate: Callable[[Any], bool] | None = None,
) -> FeatureSpec:
    """Provisionally override the threshold and/or predicate for an experimental feature."""
    if name not in EXPERIMENTAL_REGISTRY:
        raise KeyError(f"Feature '{name}' not found in experimental registry")
    old = EXPERIMENTAL_REGISTRY[name]
    new_spec = FeatureSpec(
        name=old.name,
        scalar_type=old.scalar_type,
        description=old.description,
        default_predicate=predicate or old.default_predicate,
        optimal_threshold=new_threshold,
        hypothesis_ref=old.hypothesis_ref,
        default_group=old.default_group,
    )
    EXPERIMENTAL_REGISTRY[name] = new_spec
    return new_spec


def reset_to_production() -> None:
    """Reset experimental registry back to exact production specs."""
    EXPERIMENTAL_REGISTRY.clear()
    EXPERIMENTAL_REGISTRY.update(
        {name: copy(spec) for name, spec in FEATURE_REGISTRY.items()}
    )


def get_production_features() -> dict[str, FeatureSpec]:
    """Return only the features present in the production registry."""
    return {
        name: EXPERIMENTAL_REGISTRY[name]
        for name in FEATURE_REGISTRY
        if name in EXPERIMENTAL_REGISTRY
    }


def get_experimental_features() -> dict[str, FeatureSpec]:
    """Return features registered only in the experimental registry."""
    return {
        name: spec
        for name, spec in EXPERIMENTAL_REGISTRY.items()
        if name not in FEATURE_REGISTRY
    }


__all__ = [
    "EXPERIMENTAL_REGISTRY",
    "get_experimental_features",
    "get_production_features",
    "override_threshold",
    "register_experimental",
    "reset_to_production",
]
