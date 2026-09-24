"""Production Feature Registry for text and layout scalar properties.

Defines the canonical metadata, scalar types, and data-driven threshold
predicates for all properties extracted from text blocks.

Calibrated using scikit-learn optimal information-gain decision splits
across 3,411 ground-truth acceptance blocks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Metadata specification for a single scalar feature."""

    name: str
    scalar_type: type  # int, float, bool
    description: str
    default_predicate: Callable[[Any], bool]
    optimal_threshold: float | None = None
    hypothesis_ref: str | None = None
    default_group: str | None = None


# Registry mapping feature name to its FeatureSpec
FEATURE_REGISTRY: dict[str, FeatureSpec] = {}


def _register(
    name: str,
    scalar_type: type,
    description: str,
    default_predicate: Callable[[Any], bool],
    optimal_threshold: float | None = None,
    hypothesis_ref: str | None = None,
    default_group: str | None = None,
) -> FeatureSpec:
    spec = FeatureSpec(
        name=name,
        scalar_type=scalar_type,
        description=description,
        default_predicate=default_predicate,
        optimal_threshold=optimal_threshold,
        hypothesis_ref=hypothesis_ref,
        default_group=default_group,
    )
    FEATURE_REGISTRY[name] = spec
    return spec


# =============================================================================
# 1. Intrinsic Binary Booleans (No arbitrary threshold needed)
# =============================================================================
_register(
    "ends_terminal_punct",
    bool,
    "Block ends with [.!?] sentence punctuation",
    bool,
    optimal_threshold=1.0,
)
_register(
    "starts_capital_or_indent",
    bool,
    "First line starts with capital letter or indent",
    bool,
    optimal_threshold=1.0,
)
_register(
    "has_table_wrapper_tag",
    bool,
    "Block contains <TABLE> or </TABLE> SGML tag",
    bool,
    optimal_threshold=1.0,
)
_register(
    "has_checkbox",
    bool,
    "Block contains checkbox grammar [ ] or [X]",
    bool,
    optimal_threshold=1.0,
)
_register(
    "is_financial_bridge",
    bool,
    "Block matches financial statement section label",
    bool,
    optimal_threshold=1.0,
)
_register(
    "has_dot_leader",
    bool,
    "Block contains dot-leader run (...)",
    bool,
    optimal_threshold=1.0,
)
_register(
    "has_separator_run",
    bool,
    "Block contains separator run (---- or ====)",
    bool,
    optimal_threshold=1.0,
)
_register(
    "has_deadspace_corridor",
    bool,
    "Persistent >= 3-col blank strip spanning all lines",
    bool,
    optimal_threshold=1.0,
    hypothesis_ref="H-GEO-14",
)
_register(
    "non_final_ends_numeric",
    bool,
    "Any non-final line ending with number, paren, or pct",
    bool,
    optimal_threshold=1.0,
)
_register(
    "is_bilateral_inset",
    bool,
    "Block has bilateral margin insets (L >= 4, R <= 74)",
    bool,
    optimal_threshold=1.0,
)

# =============================================================================
# 2. Continuous Floats (Calibrated via scikit-learn optimal decision stumps)
# =============================================================================
# function_word_ratio: prose median 0.414, table median 0.167 -> optimal split 0.299 (84.7% acc)
_register(
    "function_word_ratio",
    float,
    "Ratio of function/stop words to total words",
    lambda v: v >= 0.30,
    optimal_threshold=0.299,
)

# article_density: prose median 2.00, table median 0.00 -> optimal split 0.977 (85.5% acc)
_register(
    "article_density",
    float,
    "Articles (the, a, an) per line",
    lambda v: v >= 1.0,
    optimal_threshold=0.977,
)

# width_fill_65_ratio: prose median 1.000, table median 0.700 -> optimal split 0.989 (78.3% acc)
_register(
    "width_fill_65_ratio",
    float,
    "Fraction of lines spanning >= 65 columns",
    lambda v: v >= 0.98,
    optimal_threshold=0.989,
)

# row_template_periodicity: table median 0.261, prose median 0.000 -> optimal split 0.078 (85.2% acc)
_register(
    "row_template_periodicity",
    float,
    "Repeating normalized row shape match ratio",
    lambda v: v >= 0.08,
    optimal_threshold=0.078,
    hypothesis_ref="H-GEO-11",
)

# indent_alternation_ratio: table median 0.182, prose median 0.000 -> optimal split 0.011 (83.3% acc)
_register(
    "indent_alternation_ratio",
    float,
    "Ratio of alternating indent wraps across lines",
    lambda v: v >= 0.01,
    optimal_threshold=0.011,
    hypothesis_ref="H-GEO-12",
)

# continuation_col0_ratio: table median 0.577, prose median 0.000 -> optimal split 0.006 (82.4% acc)
_register(
    "continuation_col0_ratio",
    float,
    "Fraction of continuation lines starting at col <= 4",
    lambda v: v >= 0.01,
    optimal_threshold=0.006,
)

# rewrap_residual: table median 0.188, prose median 0.000 -> optimal split 0.001 (83.2% acc)
_register(
    "rewrap_residual",
    float,
    "Greedy line-wrap distortion residual",
    lambda v: v <= 0.001,
    optimal_threshold=0.001,
    hypothesis_ref="H-GEO-13",
)

# soft_wrap_ratio: optimal split 0.004 (61.7% acc)
_register(
    "soft_wrap_ratio",
    float,
    "Fraction of interline boundaries that are soft wraps",
    lambda v: v > 0.0,
    optimal_threshold=0.004,
)

# grammatical_comma_ratio: optimal split 0.411 (62.6% acc)
_register(
    "grammatical_comma_ratio",
    float,
    "Ratio of prose commas (a, b) to all commas",
    lambda v: v >= 0.40,
    optimal_threshold=0.411,
)

# row_shape_autocorrelation: optimal split 0.0 (69.0% acc)
_register(
    "row_shape_autocorrelation",
    float,
    "Autocorrelation of numeric cell counts across rows",
    lambda v: v > 0.0,
    optimal_threshold=0.0,
    hypothesis_ref="H-GEO-16",
)

# Window alpha densities (horizontal slices 0-20, 21-40, 41-60, 61-80)
_register(
    "alpha_density_w1",
    float,
    "Alpha char density in cols 0-20",
    lambda v: v >= 0.90,
    optimal_threshold=0.984,
)
_register(
    "alpha_density_w2",
    float,
    "Alpha char density in cols 21-40",
    lambda v: v >= 0.80,
    optimal_threshold=0.806,
)
_register(
    "alpha_density_w3",
    float,
    "Alpha char density in cols 41-60",
    lambda v: v >= 0.56,
    optimal_threshold=0.562,
)
_register(
    "alpha_density_w4",
    float,
    "Alpha char density in cols 61-80",
    lambda v: v >= 0.65,
    optimal_threshold=0.686,
)

# Window numeric densities (horizontal slices)
_register(
    "numeric_density_w1",
    float,
    "Numeric char density in cols 0-20",
    lambda v: v >= 0.03,
    optimal_threshold=0.030,
)
_register(
    "numeric_density_w2",
    float,
    "Numeric char density in cols 21-40",
    lambda v: v >= 0.01,
    optimal_threshold=0.001,
)
_register(
    "numeric_density_w3",
    float,
    "Numeric char density in cols 41-60",
    lambda v: v >= 0.13,
    optimal_threshold=0.133,
)
_register(
    "numeric_density_w4",
    float,
    "Numeric char density in cols 61-80",
    lambda v: v >= 0.13,
    optimal_threshold=0.128,
)

# =============================================================================
# 3. Discrete Counts & Integers (Calibrated via scikit-learn optimal decision stumps)
# =============================================================================
# gutter_4_col_count: table median 6.0, prose median 0.0 -> optimal split 1.5 (98.4% acc)
_register(
    "gutter_4_col_count",
    int,
    "Max recurrence of >= 4-space column gap across lines",
    lambda v: v >= 2,
    optimal_threshold=1.5,
)

# cell_edge_aligned_count: table median 6.0, prose median 0.0 -> optimal split 2.5 (87.7% acc)
_register(
    "cell_edge_aligned_count",
    int,
    "Count of shared right-margin or decimal alignments",
    lambda v: v >= 3,
    optimal_threshold=2.5,
    hypothesis_ref="H-GEO-18",
)

# stub_gutter_numeric_count: table median 4.0, prose median 0.0 -> optimal split 0.5 (86.1% acc)
_register(
    "stub_gutter_numeric_count",
    int,
    "Lines matching text stub -> gap -> numeric cell",
    lambda v: v >= 1,
    optimal_threshold=0.5,
    hypothesis_ref="H-GEO-17",
)

# line_count: table median 17.0, prose median 1.0 -> optimal split 3.5 (86.7% acc)
_register(
    "line_count",
    int,
    "Number of non-blank lines in block",
    lambda v: v >= 4,
    optimal_threshold=3.5,
)

# column_underline_count: table median 1.0, prose median 0.0 -> optimal split 0.5 (81.4% acc)
_register(
    "column_underline_count",
    int,
    "Count of short column-underline dash rules (---   ---)",
    lambda v: v >= 1,
    optimal_threshold=0.5,
)

# inset_measure_width: optimal split 134.5 (76.7% acc)
_register(
    "inset_measure_width",
    int,
    "Width span (R - L) of bilateral inset block",
    lambda v: 0 < v <= 135,
    optimal_threshold=134.5,
)

# Linguistic occurrence counts (0 vs > 0)
_register(
    "relative_clause_count",
    int,
    "Count of which, that, whereby, wherein",
    lambda v: v > 0,
    optimal_threshold=0.5,
)
_register(
    "possessive_count",
    int,
    "Raw count of possessive 's tokens",
    lambda v: v > 0,
    optimal_threshold=0.5,
)
_register(
    "soft_wrap_count",
    int,
    "Lines ending in alpha/comma where next line starts lowercase",
    lambda v: v > 0,
    optimal_threshold=0.5,
)
_register(
    "connector_wrap_count",
    int,
    "Lines ending with dangling prepositions or determiners",
    lambda v: v > 0,
    optimal_threshold=0.5,
)
_register(
    "prose_phrase_right_half_count",
    int,
    "Prose phrases in right half of content width",
    lambda v: v > 0,
    optimal_threshold=0.5,
)
_register(
    "semicolon_count",
    int,
    "Raw count of semicolons (;)",
    lambda v: v > 0,
    optimal_threshold=0.5,
)
_register(
    "verbal_participle_count",
    int,
    "Count of -ing and -ed verbal participles",
    lambda v: v > 0,
    optimal_threshold=42.5,
)
_register(
    "narrative_date_count",
    int,
    "Count of full calendar date mentions (Month DD, YYYY)",
    lambda v: v > 0,
    optimal_threshold=2.5,
)
_register(
    "exhibit_numbering_count",
    int,
    "Count of exhibit index numbers (e.g. 10.1, 10(a))",
    lambda v: v > 0,
    optimal_threshold=4.5,
)
_register(
    "exhibit_phrase_count",
    int,
    "Count of exhibit phrases (e.g. filed herewith)",
    lambda v: v > 0,
    optimal_threshold=0.5,
)


__all__ = [
    "FEATURE_REGISTRY",
    "FeatureSpec",
]
