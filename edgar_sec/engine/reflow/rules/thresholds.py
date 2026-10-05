"""Calibrated metadata for every scalar feature a reflow block exposes.
A `FeatureSpec` carries what a measurement is, its Python type, and the predicate deciding whether a value counts as evidence, so one table is the only place a threshold can change. Where `optimal_threshold` and the predicate disagree, the predicate runs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Metadata specification for a single scalar feature."""

    name: str
    scalar_type: type
    description: str
    default_predicate: Callable[[Any], bool]
    optimal_threshold: float | None = None
    hypothesis_ref: str | None = None
    default_group: str | None = None


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

_register(
    "function_word_ratio",
    float,
    "Ratio of function/stop words to total words",
    lambda v: v >= 0.30,
    optimal_threshold=0.299,
)

_register(
    "article_density",
    float,
    "Articles (the, a, an) per line",
    lambda v: v >= 1.0,
    optimal_threshold=0.977,
)

_register(
    "width_fill_65_ratio",
    float,
    "Fraction of lines spanning >= 65 columns",
    lambda v: v >= 0.98,
    optimal_threshold=0.989,
)

_register(
    "row_template_periodicity",
    float,
    "Repeating normalized row shape match ratio",
    lambda v: v >= 0.08,
    optimal_threshold=0.078,
    hypothesis_ref="H-GEO-11",
)

_register(
    "indent_alternation_ratio",
    float,
    "Ratio of alternating indent wraps across lines",
    lambda v: v >= 0.01,
    optimal_threshold=0.011,
    hypothesis_ref="H-GEO-12",
)

_register(
    "continuation_col0_ratio",
    float,
    "Fraction of continuation lines starting at col <= 4",
    lambda v: v >= 0.01,
    optimal_threshold=0.006,
)

_register(
    "rewrap_residual",
    float,
    "Greedy line-wrap distortion residual",
    lambda v: v <= 0.001,
    optimal_threshold=0.001,
    hypothesis_ref="H-GEO-13",
)

_register(
    "soft_wrap_ratio",
    float,
    "Fraction of interline boundaries that are soft wraps",
    lambda v: v > 0.0,
    optimal_threshold=0.004,
)

_register(
    "grammatical_comma_ratio",
    float,
    "Ratio of prose commas (a, b) to all commas",
    lambda v: v >= 0.40,
    optimal_threshold=0.411,
)

_register(
    "row_shape_autocorrelation",
    float,
    "Autocorrelation of numeric cell counts across rows",
    lambda v: v > 0.0,
    optimal_threshold=0.0,
    hypothesis_ref="H-GEO-16",
)

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

_register(
    "gutter_4_col_count",
    int,
    "Max recurrence of >= 4-space column gap across lines",
    lambda v: v >= 2,
    optimal_threshold=1.5,
)

_register(
    "cell_edge_aligned_count",
    int,
    "Count of shared right-margin or decimal alignments",
    lambda v: v >= 3,
    optimal_threshold=2.5,
    hypothesis_ref="H-GEO-18",
)

_register(
    "stub_gutter_numeric_count",
    int,
    "Lines matching text stub -> gap -> numeric cell",
    lambda v: v >= 1,
    optimal_threshold=0.5,
    hypothesis_ref="H-GEO-17",
)

_register(
    "line_count",
    int,
    "Number of non-blank lines in block",
    lambda v: v >= 4,
    optimal_threshold=3.5,
)

_register(
    "column_underline_count",
    int,
    "Count of short column-underline dash rules (---   ---)",
    lambda v: v >= 1,
    optimal_threshold=0.5,
)

_register(
    "inset_measure_width",
    int,
    "Width span (R - L) of bilateral inset block",
    lambda v: 0 < v <= 135,
    optimal_threshold=134.5,
)

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
