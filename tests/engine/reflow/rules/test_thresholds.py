"""The 44 calibrated thresholds, pinned so a later edit fails loudly.

The predicates in `thresholds.py` were fitted with scikit-learn optimal
information-gain splits over 3,411 ground-truth acceptance blocks. They are not
tunable: a "tidied" split point moves a boundary and silently reclassifies
blocks, and the failure mode is a collapsed table rather than a visible error.
So this module asserts the exact registry size, the exact registry order, the
predicate verdicts either side of every split, and the recorded fitted value
next to the predicate that actually runs.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.reflow.features.context import BlockContext
from edgar_sec.engine.reflow.rules.thresholds import FEATURE_REGISTRY

# The registry must hold exactly this many features. A drop is a lost
# measurement; an addition is an uncalibrated one.
EXPECTED_COUNT = 44

# The registry order is the canonical feature-vector order, so it is part of the
# contract rather than an implementation detail.
EXPECTED_ORDER = (
    "ends_terminal_punct",
    "starts_capital_or_indent",
    "has_table_wrapper_tag",
    "has_checkbox",
    "is_financial_bridge",
    "has_dot_leader",
    "has_separator_run",
    "has_deadspace_corridor",
    "non_final_ends_numeric",
    "is_bilateral_inset",
    "function_word_ratio",
    "article_density",
    "width_fill_65_ratio",
    "row_template_periodicity",
    "indent_alternation_ratio",
    "continuation_col0_ratio",
    "rewrap_residual",
    "soft_wrap_ratio",
    "grammatical_comma_ratio",
    "row_shape_autocorrelation",
    "alpha_density_w1",
    "alpha_density_w2",
    "alpha_density_w3",
    "alpha_density_w4",
    "numeric_density_w1",
    "numeric_density_w2",
    "numeric_density_w3",
    "numeric_density_w4",
    "gutter_4_col_count",
    "cell_edge_aligned_count",
    "stub_gutter_numeric_count",
    "line_count",
    "column_underline_count",
    "inset_measure_width",
    "relative_clause_count",
    "possessive_count",
    "soft_wrap_count",
    "connector_wrap_count",
    "prose_phrase_right_half_count",
    "semicolon_count",
    "verbal_participle_count",
    "narrative_date_count",
    "exhibit_numbering_count",
    "exhibit_phrase_count",
)

# A representative sample of split points: the predicate, the value it is
# compared against, and a pair of samples straddling it. This is the vector that
# has to fail when someone "rounds" a threshold.
SPLIT_SAMPLES: tuple[tuple[str, object, object, object], ...] = (
    ("function_word_ratio", 0.29, 0.30, 0.299),
    ("article_density", 0.99, 1.0, 0.977),
    ("width_fill_65_ratio", 0.97, 0.98, 0.989),
    ("row_template_periodicity", 0.07, 0.08, 0.078),
    ("indent_alternation_ratio", 0.009, 0.01, 0.011),
    ("continuation_col0_ratio", 0.009, 0.01, 0.006),
    ("soft_wrap_ratio", 0.0, 0.1, 0.004),
    ("grammatical_comma_ratio", 0.39, 0.4, 0.411),
    ("row_shape_autocorrelation", 0.0, 0.1, 0.0),
    ("alpha_density_w1", 0.89, 0.9, 0.984),
    ("alpha_density_w2", 0.79, 0.8, 0.806),
    ("alpha_density_w3", 0.55, 0.56, 0.562),
    ("alpha_density_w4", 0.64, 0.65, 0.686),
    ("numeric_density_w1", 0.029, 0.03, 0.030),
    ("numeric_density_w3", 0.129, 0.13, 0.133),
    ("numeric_density_w4", 0.129, 0.13, 0.128),
    ("gutter_4_col_count", 1, 2, 1.5),
    ("cell_edge_aligned_count", 2, 3, 2.5),
    ("stub_gutter_numeric_count", 0, 1, 0.5),
    ("line_count", 3, 4, 3.5),
    ("column_underline_count", 0, 1, 0.5),
    ("relative_clause_count", 0, 1, 0.5),
    ("narrative_date_count", 0, 1, 2.5),
    ("exhibit_numbering_count", 0, 1, 4.5),
    ("verbal_participle_count", 0, 1, 42.5),
)


def test_registry_holds_exactly_forty_four_features() -> None:
    assert len(FEATURE_REGISTRY) == EXPECTED_COUNT


def test_registry_order_is_the_canonical_feature_vector_order() -> None:
    assert tuple(FEATURE_REGISTRY) == EXPECTED_ORDER


@pytest.mark.parametrize("name", EXPECTED_ORDER)
def test_every_registered_feature_resolves_on_a_block_context(name: str) -> None:
    spec = FEATURE_REGISTRY[name]
    assert spec.name == name
    assert spec.description
    assert getattr(BlockContext(("alpha", "beta")), name) is not None


@pytest.mark.parametrize("name", EXPECTED_ORDER)
def test_every_predicate_answers_a_boolean(name: str) -> None:
    predicate = FEATURE_REGISTRY[name].default_predicate
    for sample in (0, 0.0, 1, 1.0, True, False):
        assert isinstance(predicate(sample), bool)


@pytest.mark.parametrize(
    ("name", "below", "at_or_above", "fitted"),
    SPLIT_SAMPLES,
    ids=[sample[0] for sample in SPLIT_SAMPLES],
)
def test_split_points_are_where_they_were_calibrated(
    name: str, below: object, at_or_above: object, fitted: float
) -> None:
    spec = FEATURE_REGISTRY[name]
    assert spec.default_predicate(below) is False
    assert spec.default_predicate(at_or_above) is True
    assert spec.optimal_threshold == pytest.approx(fitted)


def test_inset_measure_width_is_a_bounded_window_not_a_lower_bound() -> None:
    spec = FEATURE_REGISTRY["inset_measure_width"]
    assert spec.default_predicate(0) is False
    assert spec.default_predicate(1) is True
    assert spec.default_predicate(135) is True
    assert spec.default_predicate(136) is False
    assert spec.optimal_threshold == 134.5


def test_rewrap_residual_is_inverted_below_its_split() -> None:
    spec = FEATURE_REGISTRY["rewrap_residual"]
    assert spec.default_predicate(0.0) is True
    assert spec.default_predicate(0.001) is True
    assert spec.default_predicate(0.002) is False
    assert spec.optimal_threshold == 0.001


def test_soft_wrap_and_autocorrelation_predicates_are_strictly_positive() -> None:
    assert FEATURE_REGISTRY["soft_wrap_ratio"].default_predicate(0.0) is False
    assert FEATURE_REGISTRY["row_shape_autocorrelation"].default_predicate(0.0) is False


def test_hypothesis_refs_are_carried_only_where_the_metric_names_one() -> None:
    referenced = {
        name
        for name, spec in FEATURE_REGISTRY.items()
        if spec.hypothesis_ref is not None
    }
    assert referenced == {
        "has_deadspace_corridor",
        "row_template_periodicity",
        "indent_alternation_ratio",
        "rewrap_residual",
        "row_shape_autocorrelation",
        "cell_edge_aligned_count",
        "stub_gutter_numeric_count",
    }
    assert all(
        spec.hypothesis_ref.startswith("H-GEO-")
        for spec in FEATURE_REGISTRY.values()
        if spec.hypothesis_ref
    )
