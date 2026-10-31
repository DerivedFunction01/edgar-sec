"""Contract tests for TOC line analysis and normalization."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.toc.analysis import (
    is_anachronistic_late_item,
    is_toc_row,
    looks_like_toc_row,
    looks_like_toc_tabular,
    normalize_for_matching,
    score_block_toc_density,
)


def test_normalize_for_matching_folds_punctuation_to_single_spaces() -> None:
    assert normalize_for_matching("Item 1A. Risk Factors (8)") == (
        "item 1a risk factors 8"
    )


def test_normalize_for_matching_of_blank_text_is_empty() -> None:
    assert normalize_for_matching("") == ""
    assert normalize_for_matching("   ") == ""


def test_row_predicates_agree_on_a_dot_leader_row() -> None:
    assert is_toc_row("ITEM 1. BUSINESS .... 1") is True
    assert looks_like_toc_row("ITEM 1. BUSINESS .... 1") is True


def test_body_prose_is_not_a_toc_row() -> None:
    assert is_toc_row("We are an enterprise software company.") is False


def test_tabular_toc_shape_requires_a_dot_leader_and_a_page_token() -> None:
    assert looks_like_toc_tabular("Item 1 - Business .............. 1") is True
    assert looks_like_toc_tabular("Item 1 - Business") is False
    assert looks_like_toc_tabular("") is False


def test_block_density_counts_matching_keywords() -> None:
    count, hits = score_block_toc_density(
        "item 1 business and properties", ("item", "business")
    )

    assert count == 2
    assert hits == ("item", "business")


def test_block_density_of_blank_text_is_zero() -> None:
    assert score_block_toc_density("", ("item",)) == (0, ())


def test_anachronistic_late_item_matches_a_late_item_expression() -> None:
    import re

    assert (
        is_anachronistic_late_item("ITEM 15. EXHIBITS", re.compile(r"^\s*ITEM\s+15"))
        is True
    )
    assert (
        is_anachronistic_late_item("ITEM 1. BUSINESS", re.compile(r"^\s*ITEM\s+15"))
        is False
    )


def test_anachronistic_late_item_ignores_blank_and_lowercase_prose() -> None:
    assert is_anachronistic_late_item("   ") is False
    assert (
        is_anachronistic_late_item("item 15. exhibits", None, ("item 15 exhibits",))
        is False
    )


def test_anachronistic_late_item_accepts_a_normalized_name() -> None:
    assert (
        is_anachronistic_late_item("ITEM 15. EXHIBITS", None, ("item 15 exhibits",))
        is True
    )
