"""Unit tests for the Two-Tier Feature Registry separation."""

from __future__ import annotations

from defs.text.reflow.registry import FEATURE_REGISTRY
from defs.text.reflow.tools.clustering.registry import (
    EXPERIMENTAL_REGISTRY,
    get_experimental_features,
    get_production_features,
    override_threshold,
    register_experimental,
    reset_to_production,
)


def test_registry_initial_state() -> None:
    # Initially, experimental registry mirrors production
    assert len(EXPERIMENTAL_REGISTRY) == len(FEATURE_REGISTRY)
    assert len(get_production_features()) == len(FEATURE_REGISTRY)
    assert len(get_experimental_features()) == 0


def test_register_experimental_feature() -> None:
    reset_to_production()
    initial_prod_len = len(FEATURE_REGISTRY)

    spec = register_experimental(
        name="test_speculative_signal",
        scalar_type=float,
        description="A test candidate feature",
        default_predicate=lambda v: v > 0.5,
        optimal_threshold=0.5,
        hypothesis_ref="H-EXP-01",
        default_group="experimental",
    )
    assert spec.name == "test_speculative_signal"
    assert "test_speculative_signal" in EXPERIMENTAL_REGISTRY
    # Production registry remains UNTOUCHED
    assert "test_speculative_signal" not in FEATURE_REGISTRY
    assert len(FEATURE_REGISTRY) == initial_prod_len
    assert len(get_experimental_features()) == 1

    # Clean up
    reset_to_production()
    assert "test_speculative_signal" not in EXPERIMENTAL_REGISTRY


def test_override_threshold() -> None:
    reset_to_production()
    orig_prod_thresh = FEATURE_REGISTRY["line_count"].optimal_threshold

    new_spec = override_threshold("line_count", 10.0)
    assert new_spec.optimal_threshold == 10.0
    assert EXPERIMENTAL_REGISTRY["line_count"].optimal_threshold == 10.0
    # Production registry remains UNTOUCHED
    assert FEATURE_REGISTRY["line_count"].optimal_threshold == orig_prod_thresh

    # Reset
    reset_to_production()
    assert EXPERIMENTAL_REGISTRY["line_count"].optimal_threshold == orig_prod_thresh
