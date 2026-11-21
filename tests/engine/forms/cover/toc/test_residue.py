"""Contract tests for TOC residue consumption."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.toc.residue import consume_toc_residue

LINES = [
    "TABLE OF CONTENTS",
    "PART I .................................. 1",
    "ITEM 1. BUSINESS ....................... 4",
    "notes.",
    "1",
    "",
    "PART I",
    "ITEM 1. BUSINESS",
    "We are an enterprise software company.",
    "Our customers include major healthcare providers.",
]


def test_residue_stops_at_the_first_non_toc_prose() -> None:
    assert consume_toc_residue(LINES, 0, len(LINES)) == 2


def test_residue_is_a_no_op_on_a_non_toc_line() -> None:
    assert consume_toc_residue(LINES, 2, len(LINES)) == 2


def test_residue_skips_ascii_separator_rules() -> None:
    lines = ["PART I ....... 1", "+----------------+", "notes."]

    assert consume_toc_residue(lines, 0, len(lines)) == 2


def test_residue_is_a_no_op_at_the_limit() -> None:
    assert consume_toc_residue(LINES, len(LINES), len(LINES)) == len(LINES)


def test_bullet_lines_are_consumed_as_residue() -> None:
    lines = ["* footnote note", "body prose follows here"]

    assert consume_toc_residue(lines, 0, len(lines)) == 1
