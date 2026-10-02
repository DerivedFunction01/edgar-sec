"""Memoized block feature context, and the two features it cannot measure alone.

The context is the rule cascade's only input, so the tests pin both the
measurements and the injection seam: `has_checkbox` and `is_financial_bridge`
are the two features whose answer belongs to the caller's form vocabulary, and
this module must read them off the policy rather than import a form family.
"""

from __future__ import annotations

import subprocess
import sys

from edgar_sec.engine.reflow.features.context import BlockContext
from edgar_sec.engine.reflow.rules.thresholds import FEATURE_REGISTRY
from edgar_sec.engine.reflow.types import ReflowPolicy

PROSE = (
    "We are an enterprise software company",
    "founded in 1998 that sells products",
    "across multiple market segments today.",
)

TABLE = (
    "Revenue by segment       2024       2023",
    "  Automotive             $1,200     $1,100",
    "  Industrial             $2,050     $1,980",
)

PRODUCTION_POLICY = ReflowPolicy(
    is_checkbox_answer_line=lambda line: "Yes [X]" in line,
    is_table_bridge_line=lambda line: line.isupper(),
)


def _context(
    lines: tuple[str, ...], policy: ReflowPolicy | None = None
) -> BlockContext:
    return BlockContext(lines, policy)


def test_context_accepts_raw_text_and_splits_into_lines() -> None:
    context = BlockContext("alpha\nbeta\n\ngamma")
    assert context.raw_text == "alpha\nbeta\n\ngamma"
    assert context.raw_lines == ("alpha", "beta", "", "gamma")
    assert context.non_blank_lines == ("alpha", "beta", "gamma")
    assert context.line_count == 3
    assert context.non_blank == 3


def test_context_accepts_a_line_sequence_verbatim() -> None:
    lines = ("alpha", "  beta  ")
    context = BlockContext(lines)
    assert context.raw_lines == lines
    assert context.raw_text == "alpha\n  beta  "


def test_context_accepts_a_list_and_freezes_it() -> None:
    lines = ["alpha", "beta"]
    context = BlockContext(lines)
    lines.append("gamma")
    assert context.raw_lines == ("alpha", "beta")


def test_every_registered_feature_resolves_on_an_empty_block() -> None:
    context = _context(())
    for name in FEATURE_REGISTRY:
        getattr(context, name)


def test_every_registered_feature_resolves_on_a_text_block() -> None:
    context = _context(PROSE, PRODUCTION_POLICY)
    for name in FEATURE_REGISTRY:
        getattr(context, name)


def test_feature_dict_covers_the_registry_in_order() -> None:
    context = _context(PROSE, PRODUCTION_POLICY)
    features = context.to_feature_dict()
    assert tuple(features) == tuple(FEATURE_REGISTRY)
    assert features["line_count"] == 3


def test_feature_floats_is_the_registry_in_canonical_order() -> None:
    context = _context(PROSE, PRODUCTION_POLICY)
    values = context.to_feature_floats()
    assert len(values) == len(FEATURE_REGISTRY)
    assert all(type(value) is float for value in values)
    expected = tuple(
        1.0
        if spec.scalar_type is bool and getattr(context, name)
        else 0.0
        if spec.scalar_type is bool
        else float(getattr(context, name))
        for name, spec in FEATURE_REGISTRY.items()
    )
    assert values == expected


def test_feature_floats_encodes_booleans_as_one_and_zero() -> None:
    context = _context(PROSE, PRODUCTION_POLICY)
    values = context.to_feature_floats()
    checkbox_index = tuple(FEATURE_REGISTRY).index("has_checkbox")
    assert values[checkbox_index] in (0.0, 1.0)
    assert type(values[checkbox_index]) is float


def test_feature_floats_does_not_drag_numpy_into_the_import_graph() -> None:
    """A dense vector is not part of the engine's contract.

    The only V1 consumer of the array form was the offline ML labelling
    harness, which is not ported. An array here would put numpy in the import
    graph of every process that normalizes a filing, so importing this module
    in a clean interpreter must not import numpy.
    """
    probe = (
        "import sys\n"
        "import edgar_sec.engine.reflow.features.context\n"
        "print('numpy' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"


def test_has_separator_aliases_the_run_feature() -> None:
    context = _context(("-------   --------", "a   b   c"))
    assert context.has_separator_run is True
    assert context.has_separator is context.has_separator_run


def test_column_underline_counts_dash_rules_and_separator_lines() -> None:
    assert _context(("-----   -----", "x   y")).column_underline_count == 1
    assert _context(("==========", "x   y")).column_underline_count == 1
    assert _context(("plain prose", "more prose")).column_underline_count == 0


def test_has_dot_leader_requires_a_dot_in_the_raw_text() -> None:
    assert _context(("Item 1. Business ................. 1",)).has_dot_leader is True
    assert _context(("a.b.c",)).has_dot_leader is False


def test_has_table_wrapper_tag_is_case_insensitive() -> None:
    assert _context(("<table>x</table>",)).has_table_wrapper_tag is True
    assert _context(("plain",)).has_table_wrapper_tag is False


def test_ends_terminal_punct_and_starts_capital_are_edge_safe() -> None:
    assert _context(()).ends_terminal_punct is False
    assert _context(()).starts_capital_or_indent is False
    assert _context(("It ends here.",)).ends_terminal_punct is True
    assert _context(("  indented lower",)).starts_capital_or_indent is True
    assert _context(("lower",)).starts_capital_or_indent is False


def test_has_checkbox_fires_on_the_mark_without_a_predicate() -> None:
    assert _context(("Large accelerated filer [X]",)).has_checkbox is True
    assert _context(("Large accelerated filer",)).has_checkbox is False


def test_has_checkbox_uses_the_injected_predicate() -> None:
    # The mark vocabulary alone cannot see this line, so a True here is
    # attributable only to the policy the caller injected.
    lines = ("Yes the registrant checked the large accelerated filer box",)
    assert _context(lines).has_checkbox is False
    assert _context(lines, PRODUCTION_POLICY).has_checkbox is False
    permissive = ReflowPolicy(
        is_checkbox_answer_line=lambda line: line.startswith("Yes")
    )
    assert _context(lines, permissive).has_checkbox is True


def test_is_financial_bridge_is_false_without_an_injected_predicate() -> None:
    lines = ("LIABILITIES AND STOCKHOLDERS' EQUITY",)
    assert _context(lines).is_financial_bridge is False
    assert _context(lines, PRODUCTION_POLICY).is_financial_bridge is True


def test_is_financial_bridge_scans_every_non_blank_line() -> None:
    lines = ("Common stock                       24,818", "LIABILITIES")
    assert _context(lines, PRODUCTION_POLICY).is_financial_bridge is True


def test_shared_numeric_columns_requires_three_rows() -> None:
    assert _context(("a   1", "b   2")).shared_numeric_columns == 0
    assert _context(("a   1", "b   2", "c   3")).shared_numeric_columns == 1


def test_shared_gaps_count_measures_whitespace_columns() -> None:
    assert _context(("a   b", "c   d", "e   f")).shared_gaps_count == 1
    assert _context(("prose here", "more prose")).shared_gaps_count == 0


def test_numeric_row_density_is_rows_over_non_blank_lines() -> None:
    context = _context(("a   1", "b   2", "prose line"))
    assert context.numeric_cell_row_count == 2
    assert context.numeric_row_density == 2 / 3


def test_max_gap_ignores_leading_indentation() -> None:
    assert _context(("        deeply indented prose",)).max_gap == 0


def test_gutter_count_needs_a_four_space_gap_on_two_lines() -> None:
    assert _context(("a    b",)).gutter_4_col_count == 0
    assert _context(("a    b", "c    d")).gutter_4_col_count == 2


def test_deadspace_corridor_needs_three_lines_and_a_wide_block() -> None:
    narrow = ("a      b", "c      d", "e      f")
    assert _context(narrow).has_deadspace_corridor is False
    wide = (
        "Item 1. Business " + " " * 40 + "1",
        "Item 1A. Risk Factors " + " " * 33 + "5",
        "Item 2. Properties " + " " * 36 + "10",
    )
    assert _context(wide).has_deadspace_corridor is True


def test_window_densities_split_the_line_into_four_horizontal_slices() -> None:
    context = _context(("word " * 40, "word " * 40))
    assert context.alpha_density_w1 == context._window_densities[0][0]
    assert context.numeric_density_w4 == context._window_densities[1][3]


def test_window_densities_on_an_empty_block_are_all_zero() -> None:
    context = _context(())
    assert context.alpha_density_w1 == 0.0
    assert context.numeric_density_w4 == 0.0


def test_soft_wrap_ratio_is_the_boundary_fraction() -> None:
    context = _context(("The company sells", "products to customers.", "ITEM 2"))
    assert context.soft_wrap_count == 1
    assert context.soft_wrap_ratio == 0.5


def test_rewrap_residual_is_zero_for_a_greedy_eighty_column_layout() -> None:
    greedy = " ".join(["word"] * 16)
    assert len(greedy) == 79
    assert _context((greedy,) * 4).rewrap_residual == 0.0


def test_rewrap_residual_is_large_for_a_ragged_block() -> None:
    ragged = (
        "short",
        "a much longer line of prose that runs on past the greedy wrap width of eighty",
        "x",
    )
    assert _context(ragged).rewrap_residual > 0.5


def test_rewrap_residual_is_zero_for_a_block_too_short_to_measure() -> None:
    assert _context(("a line", "another line")).rewrap_residual == 0.0


def test_row_shape_autocorrelation_is_one_for_a_uniform_numeric_block() -> None:
    context = _context(("a 1 2", "b 3 4", "c 5 6", "d 7 8"))
    assert context.row_shape_autocorrelation == 1.0


def test_row_shape_autocorrelation_is_zero_for_a_single_row_block() -> None:
    assert _context(("a 1 2", "b", "c")).row_shape_autocorrelation == 0.0


def test_bilateral_inset_needs_four_columns_of_left_margin() -> None:
    inset = tuple("    " + "x" * 40 for _ in range(3))
    assert _context(inset).is_bilateral_inset is True
    assert _context(("x" * 40,) * 3).is_bilateral_inset is False


def test_exhibit_counts_come_from_the_statutory_vocabulary() -> None:
    index = (
        "Exhibit Index",
        "10.1  Agreement and Plan of Merger is filed herewith.",
    )
    context = _context(index)
    assert context.exhibit_phrase_count > 0
    assert context.exhibit_numbering_count > 0


def test_narrative_date_count_is_zero_without_a_digit() -> None:
    assert _context(PROSE).narrative_date_count == 0
    assert _context(("Revenue rose on March 1, 2024.",)).narrative_date_count == 1


def test_properties_are_memoized_on_the_instance() -> None:
    context = _context(PROSE, PRODUCTION_POLICY)
    assert context.alpha_density is context.alpha_density


def test_context_does_not_import_a_form_family() -> None:
    from pathlib import Path

    import edgar_sec.engine.reflow.features.context as module

    source = Path(str(module.__file__))
    text = source.read_text(encoding="utf-8")
    assert "engine.forms" not in text
    assert "taxonomy.components" not in text
