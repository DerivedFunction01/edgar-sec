"""Contract tests for cover transition detection."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import BodyEvidencePack
from edgar_sec.engine.forms.cover.boundary.transition import (
    _first_body_semantic_line,
    _next_cover_transition,
)
from edgar_sec.engine.forms.cover.rules import compile_cover_rules

_RULES = compile_cover_rules(
    body_evidence=BodyEvidencePack(
        semantic_headings=("risk factors", "properties", "legal proceedings"),
    )
)


def test_the_first_proven_root_is_the_transition() -> None:
    lines = ["", "PART I", "ITEM 1. BUSINESS", "body prose here"]

    assert _next_cover_transition(lines, 0, len(lines)) == (1, "PART heading")


def test_same_role_children_of_the_reference_unit_are_not_transition_roots() -> None:
    lines = [
        "ITEM 1. BUSINESS",
        "Item 1A. Risk Factors",
        "ITEM 2. PROPERTIES",
        "body prose follows the reference unit",
    ]
    index, reason = _next_cover_transition(lines, 0, len(lines))

    assert reason == "end of incorporated-reference children"
    assert index >= 2


def test_continuation_prose_disqualifies_a_heading() -> None:
    lines = ["", "PART I", "hereof. the registrant agrees to the terms set out"]

    index, reason = _next_cover_transition(lines, 0, len(lines))

    assert reason == "end of incorporated-reference children"
    assert index == 3


def test_a_toc_heading_within_the_row_gap_is_the_transition() -> None:
    lines = ["", "TABLE OF CONTENTS", "PART I ....... 1", "body"]

    assert _next_cover_transition(lines, 0, len(lines)) == (1, "TOC heading")


def test_a_toc_heading_beyond_the_row_gap_is_not_a_transition() -> None:
    lines = ["", "TABLE OF CONTENTS"] + ["filler"] * 20 + ["PART I .... 1"]

    assert _next_cover_transition(lines, 0, len(lines)) is None


def test_the_last_child_rule_ends_the_cover_after_its_children() -> None:
    lines = ["Item 1. Business", "Item 2. Properties", "body prose follows"]

    index, reason = _next_cover_transition(lines, 0, len(lines))

    assert reason == "end of incorporated-reference children"
    assert index >= 1


def test_an_empty_reference_unit_has_no_transition() -> None:
    assert _next_cover_transition([], 0, 0) is None


def test_body_semantic_prose_inside_a_table_is_not_a_depth_guard_hit() -> None:
    lines = ["<TABLE>", "Risk Factors", "</TABLE>", "body"]

    assert _first_body_semantic_line(lines, 0, len(lines), _RULES) is None


def test_body_semantic_prose_before_the_transition_is_found() -> None:
    lines = ["Item 1. Business", "Risk Factors", "PART I"]

    assert _first_body_semantic_line(lines, 0, len(lines), _RULES) == 1


def test_reference_prose_is_excluded_from_the_depth_guard() -> None:
    lines = ["Documents incorporated by reference", "Risk Factors", "PART I"]

    assert _first_body_semantic_line(lines, 0, len(lines), _RULES) == 1


def test_a_quoted_section_heading_is_excluded_from_the_depth_guard() -> None:
    lines = ['Item 1. Business entitled "Risk Factors" and other matters', "PART I"]

    assert _first_body_semantic_line(lines, 0, len(lines), _RULES) is None
