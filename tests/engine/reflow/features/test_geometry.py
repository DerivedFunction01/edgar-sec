"""Single-pass layout geometry for a block of ASCII lines.
Covers the three primitives the resolver and the cascade both depend on: where a
column gap starts, where a numeric cell starts, which columns rows share.
"""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.signatures import (
    RE_SIGNATURE_LABEL_LINE,
    SIGNATURE_LABEL_PREFIXES,
    is_signature_label_line,
)
from edgar_sec.engine.reflow.features.geometry import (
    _compute_features,
    _line_gap_starts,
    _shared_columns,
)

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


def test_leading_indentation_is_not_a_column_gap() -> None:
    assert _line_gap_starts("    indented prose line") == ()
    assert _line_gap_starts("        deep    indent") == (12,)


def test_gap_needs_three_or_more_spaces() -> None:
    assert _line_gap_starts("a  b") == ()
    assert _line_gap_starts("a   b") == (1,)


def test_trailing_whitespace_is_not_a_gap() -> None:
    assert _line_gap_starts("value   ") == ()


def test_gap_positions_are_measured_from_the_original_line() -> None:
    assert _line_gap_starts("  Name:                  2024       2023") == (7, 29)


def test_shared_columns_needs_enough_rows() -> None:
    rows = ((1,), (2,))
    assert _shared_columns(rows, min_rows=3) == 0


def test_shared_columns_counts_a_repeated_position() -> None:
    rows = ((10, 30), (11, 31), (10, 30))
    assert _shared_columns(rows, min_rows=3) == 2


def test_shared_columns_tolerates_a_one_character_drift() -> None:
    rows = ((10, 30), (10, 31), (10, 30))
    assert _shared_columns(rows, min_rows=3) == 2


def test_shared_columns_does_not_double_count_within_tolerance() -> None:
    rows = ((10,), (11,), (10,))
    assert _shared_columns(rows, min_rows=3) == 1


def test_compute_features_on_prose_reports_no_layout() -> None:
    features = _compute_features(PROSE)
    assert features.non_blank == 3
    assert features.has_structural is False
    assert features.has_tab is False
    assert features.has_separator is False
    assert features.has_dot_leader is False
    assert features.has_signature is False
    assert features.gap_start_rows == ()
    assert features.numeric_cell_rows == ()
    assert features.shared_numeric_columns == 0
    assert features.any_lowercase is True
    assert features.alpha_density > 0.8


def test_compute_features_on_a_table_finds_the_shared_numeric_columns() -> None:
    features = _compute_features(TABLE)
    assert features.non_blank == 3
    assert features.numeric_cell_rows != ()
    assert features.shared_numeric_columns == 2
    assert features.gap_start_rows != ()


def test_compute_features_ignores_blank_lines() -> None:
    assert _compute_features(("", "   ", "")).non_blank == 0
    assert _compute_features(("", "   ", "")).alpha_density == 0.0


def test_compute_features_separates_dot_leader_from_a_leader_with_no_page() -> None:
    with_page = _compute_features(("Item 1. Business ................. 1",))
    without_page = _compute_features(("Item 1. Business .................",))
    assert with_page.has_dot_leader is True
    assert without_page.has_dot_leader is False


def test_compute_features_detects_a_tab_after_indentation() -> None:
    features = _compute_features(("  \tindented\tcolumns",))
    assert features.has_tab is True


def test_compute_features_detects_a_signature_label() -> None:
    features = _compute_features(("Date: March 1, 2024", "Title: Officer"))
    assert features.has_signature is True


def test_compute_features_detects_a_separator_run() -> None:
    features = _compute_features(("-----------------------  ---------- ----------",))
    assert features.has_separator is True


def test_compute_features_detects_structural_sgml() -> None:
    assert _compute_features(("<S>  <C>", "Assets 10 20")).has_structural is True


def test_compute_features_empty_block_is_all_zero() -> None:
    features = _compute_features(())
    assert features.non_blank == 0
    assert features.max_gap == 0
    assert features.alpha_density == 0.0
    assert features.any_lowercase is False
    assert features.shared_numeric_columns == 0


def test_signature_label_prefixes_are_the_documented_six() -> None:
    assert SIGNATURE_LABEL_PREFIXES == (
        "/s/ ",
        "By:",
        "Name:",
        "Title:",
        "Date:",
        "Signature:",
    )


def test_signature_label_line_is_case_insensitive_and_indent_tolerant() -> None:
    assert is_signature_label_line("By: /s/ Jane Doe") is True
    assert is_signature_label_line("  title: President") is True
    assert is_signature_label_line("/S/ JOHN SMITH") is True
    assert is_signature_label_line("The company signed the agreement") is False
    assert RE_SIGNATURE_LABEL_LINE.match("Signature:") is not None
