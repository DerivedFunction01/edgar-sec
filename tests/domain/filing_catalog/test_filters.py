"""Unit tests for domain.filing_catalog.filters: shared filter vocabulary.

The vocabulary lives in Layer 1 because deterministic planning and the Stage B
selection policy both need it, and the layer graph forbids the lower layer from
reaching up. These tests pin the normalization that both consumers rely on.
"""

from __future__ import annotations

from datetime import date

import pytest

from edgar_sec.domain.filing_catalog.filters import (
    AMENDMENT_POLICIES,
    DEFAULT_AMENDMENT,
    DEFAULT_DOCUMENT_SUFFIXES,
    AbsoluteDateClause,
    RecurringDateClause,
    date_selection_from_json,
    date_selection_to_json,
    format_date_selection,
    normalize_date_selection,
    normalize_suffixes,
    parse_date_selection,
)


def test_amendment_vocabulary_is_closed() -> None:
    assert AMENDMENT_POLICIES == ("both", "original", "amendments")
    assert DEFAULT_AMENDMENT in AMENDMENT_POLICIES
    assert DEFAULT_DOCUMENT_SUFFIXES == ()


def test_normalize_suffixes_lowercases_and_strips_dots() -> None:
    assert normalize_suffixes([".TXT", "xml", "  Htm "]) == ("txt", "xml", "htm")


def test_normalize_suffixes_deduplicates_but_preserves_order() -> None:
    """Order participates in the plan identity hash, so it must be stable."""
    assert normalize_suffixes(("htm", "txt", ".htm", "Htm")) == ("htm", "txt")


def test_normalize_suffixes_drops_empty_tokens() -> None:
    assert normalize_suffixes(("", "  ", ".")) == ()


def test_normalize_suffixes_rejects_quote_shaped_input() -> None:
    """v1 interpolated the suffix into a SQL literal; the allowlist is the fix."""
    for hostile in ("a'; DROP TABLE t; --", "--", "a b", "a/b", "a;b"):
        with pytest.raises(ValueError, match="invalid document suffix"):
            normalize_suffixes((hostile,))


def test_normalize_suffixes_rejects_non_string_entries() -> None:
    with pytest.raises(ValueError, match="suffix must be a string"):
        normalize_suffixes((None,))  # type: ignore[arg-type]


# --------------------------------------------------------------- date grammar


def test_empty_date_selection_is_no_predicate() -> None:
    """Empty is a distinct answer, not a spelling of any nonempty selection.

    It applies no date predicate at all, so it also keeps rows whose
    ``report_date`` is missing; a nonempty selection cannot place those rows.
    """
    assert parse_date_selection("") == ()
    assert parse_date_selection("   ") == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024", ("2024-01-01", "2024-12-31")),
        ("2024Q3", ("2024-07-01", "2024-09-30")),
        ("2024-12", ("2024-12-01", "2024-12-31")),
        ("2024-12-31", ("2024-12-31", "2024-12-31")),
        ("2005Q3..2008Q1", ("2005-07-01", "2008-03-31")),
        ("2011-12-31..2019-11-03", ("2011-12-31", "2019-11-03")),
        ("2008..", ("2008-01-01", None)),
        ("..2007", (None, "2007-12-31")),
        ("2024Q1..2024-12-31", ("2024-01-01", "2024-12-31")),
        ("2024-01-31..2024-02-01", ("2024-01-31", "2024-02-01")),
    ],
)
def test_absolute_atoms_expand_to_calendar_edges(
    text: str, expected: tuple[str | None, str | None]
) -> None:
    """Precision is the token's own shape; position decides which edge is used.

    ``2005Q3`` is July 1 when it starts a range and September 30 when it ends
    one, which is what makes a mixed-precision range mean a contiguous interval.
    """
    selection = parse_date_selection(text)
    assert selection == (
        AbsoluteDateClause(
            start_date=date.fromisoformat(expected[0]) if expected[0] else None,
            end_date=date.fromisoformat(expected[1]) if expected[1] else None,
        ),
    )


def test_quarter_atoms_span_the_whole_calendar_quarter() -> None:
    assert parse_date_selection("2024Q1") == normalize_date_selection(
        [AbsoluteDateClause(date(2024, 1, 1), date(2024, 3, 31))]
    )
    assert parse_date_selection("2024Q4") == normalize_date_selection(
        [AbsoluteDateClause(date(2024, 10, 1), date(2024, 12, 31))]
    )


def test_recurring_periods_may_bound_their_years() -> None:
    assert parse_date_selection("@Q1[2011..2015]") == normalize_date_selection(
        [RecurringDateClause("quarter", (1,), 2011, 2015)]
    )
    assert parse_date_selection("@Q2[2024..]") == normalize_date_selection(
        [RecurringDateClause("quarter", (2,), 2024, None)]
    )
    assert parse_date_selection("@M12[2024..]") == normalize_date_selection(
        [RecurringDateClause("month", (12,), 2024, None)]
    )
    assert parse_date_selection("@Q1") == normalize_date_selection(
        [RecurringDateClause("quarter", (1,), None, None)]
    )


def test_every_q1_after_2001_is_not_every_date_after_q1_2001() -> None:
    """The grammar exists because these two are different questions."""
    assert format_date_selection(parse_date_selection("@Q1[2002..]")) == "@Q1[2002..]"
    assert format_date_selection(parse_date_selection("2001Q2..")) == ("2001-04-01..")
    assert parse_date_selection("@Q1[2002..]") != parse_date_selection("2001Q2..")


def test_recurring_months_accept_one_or_two_digits() -> None:
    assert parse_date_selection("@M1") == parse_date_selection("@M01")


def test_a_selection_is_a_union_of_its_clauses() -> None:
    """Clauses OR together; the absolute ones come first in canonical order."""
    selection = parse_date_selection(
        "@Q1[1999..2001],2005Q3..2008Q1,2011-12-31..2019-11-03,@Q2[2024..]"
    )
    assert selection == normalize_date_selection(
        [
            AbsoluteDateClause(date(2005, 7, 1), date(2008, 3, 31)),
            AbsoluteDateClause(date(2011, 12, 31), date(2019, 11, 3)),
            RecurringDateClause("quarter", (1,), 1999, 2001),
            RecurringDateClause("quarter", (2,), 2024, None),
        ]
    )


@pytest.mark.parametrize(
    "text",
    [
        "Q1",
        "Q1,2023",
        "2024Q5",
        "2024Q0",
        "@Q5",
        "@Q",
        "@M13",
        "@M00",
        "@M123",
        "@X1",
        "2024-13",
        "2024-00",
        "2024-02-30",
        "2024-13-01",
        "2024-12-31T00:00:00",
        "2024/12/31",
        "20241231",
        "1800",
        "3000",
        "20",
        "..",
        "@Q1[2015..2011]",
        "@Q1[2011]",
        "@Q1[2011..2015",
        "@Q1[abc..2015]",
        "@Q1,,",
        ",@Q1",
    ],
)
def test_invalid_date_terms_are_rejected_rather_than_guessed(text: str) -> None:
    """Every term either parses or raises. Nothing is inferred."""
    with pytest.raises(ValueError):
        parse_date_selection(text)


def test_rejection_names_the_offending_term() -> None:
    with pytest.raises(ValueError, match=r"2024Q5"):
        parse_date_selection("2024,2024Q5")


def test_an_ambiguous_fully_open_range_is_refused() -> None:
    """``..`` cannot mean "every date" without colliding with the empty value."""
    with pytest.raises(ValueError, match="at least one endpoint"):
        parse_date_selection("..")


def test_inverted_bounds_are_refused() -> None:
    with pytest.raises(ValueError, match="starts after it ends"):
        parse_date_selection("2024Q3..2005Q1")


# ------------------------------------------------------------- normalization


def test_absolutely_adjacent_terms_merge_into_one_interval() -> None:
    """``2024-12-31`` and ``2025-01-01`` describe one contiguous interval."""
    assert format_date_selection(parse_date_selection("2024,2025")) == (
        "2024-01-01..2025-12-31"
    )
    assert parse_date_selection("2024-12-31,2025-01-01") == parse_date_selection(
        "2024-12-31..2025-01-01"
    )


def test_overlapping_absolute_terms_do_not_duplicate_a_window() -> None:
    assert parse_date_selection("2020..2023,2022..2024") == parse_date_selection(
        "2020..2024"
    )


def test_equivalent_recurring_periods_collapse() -> None:
    """A subsumed span must not survive as a second clause over the same years."""
    assert parse_date_selection("@Q1,@Q1[2011..2015]") == parse_date_selection("@Q1")
    assert parse_date_selection("@Q1,@Q2") == parse_date_selection("@Q2,@Q1")


def test_recurring_periods_with_different_years_stay_separate() -> None:
    """``@Q1`` is every year; restricting Q2 to 2011-2015 must not widen it."""
    assert format_date_selection(parse_date_selection("@Q1,@Q2[2011..2015]")) == (
        "@Q1[..2010],@Q1,@Q2[2011..2015],@Q1[2016..]"
    )
    selection = parse_date_selection("@Q1,@Q2[2011..2015]")
    assert selection == parse_date_selection(
        "@Q2[2011..2015],@Q1[2011..2015],@Q1[2016..],@Q1[..2010]"
    )


def test_a_selection_spanning_every_date_collapses_to_the_empty_selection() -> None:
    """``..2007`` plus ``2008..`` is every date, and the empty value is how the
    grammar spells that. Keeping a fully-open clause would also contradict the
    rule that a nonempty selection excludes rows with no readable date."""
    assert parse_date_selection("..2007,2008..") == ()
    assert format_date_selection(parse_date_selection("..2007,2008..")) == ""


def test_canonical_text_reparses_to_the_same_value() -> None:
    for text in (
        "2024",
        "2005Q3..2008Q1",
        "..2007",
        "@Q1",
        "@Q1,@Q2[2011..2015]",
        "@Q1[1999..2001],2005Q3..2008Q1,2011-12-31..2019-11-03,@Q2[2024..]",
        "@M12[2024..],@Q1",
    ):
        once = parse_date_selection(text)
        assert parse_date_selection(format_date_selection(once)) == once


def test_normalize_rejects_an_unknown_clause_type() -> None:
    with pytest.raises(ValueError, match="unknown date clause type"):
        normalize_date_selection(["2024"])  # type: ignore[list-item]


# ------------------------------------------------------------- serialization


def test_selection_serializes_to_tagged_objects_with_null_open_bounds() -> None:
    assert date_selection_to_json(parse_date_selection("2005Q3..2008Q1")) == [
        {"kind": "absolute", "start_date": "2005-07-01", "end_date": "2008-03-31"}
    ]
    assert date_selection_to_json(parse_date_selection("2008..")) == [
        {"kind": "absolute", "start_date": "2008-01-01", "end_date": None}
    ]
    assert date_selection_to_json(parse_date_selection("@Q1[1999..2001]")) == [
        {
            "kind": "recurring",
            "granularity": "quarter",
            "values": [1],
            "start_year": 1999,
            "end_year": 2001,
        }
    ]


def test_an_open_bound_is_never_resolved_against_a_current_year() -> None:
    """An open bound is a statement about intent, so persisting today's year in
    it would make an unchanged policy fingerprint differently tomorrow."""
    payload = date_selection_to_json(parse_date_selection("@Q1"))
    assert payload[0]["start_year"] is None
    assert payload[0]["end_year"] is None


def test_selection_round_trips_through_its_persisted_form() -> None:
    for text in (
        "2024",
        "2008..",
        "..2007",
        "@Q1",
        "@M12[2024..]",
        "@Q1,@Q2[2011..2015]",
        "@Q1[1999..2001],2005Q3..2008Q1,2011-12-31..2019-11-03,@Q2[2024..]",
    ):
        selection = parse_date_selection(text)
        assert date_selection_from_json(date_selection_to_json(selection)) == selection


def test_a_hand_edited_policy_document_re_canonicalizes() -> None:
    """An unordered, duplicated draft must fingerprint as the parsed selection."""
    payload = [
        {
            "kind": "recurring",
            "granularity": "quarter",
            "values": [2],
            "start_year": None,
            "end_year": None,
        },
        {
            "kind": "recurring",
            "granularity": "quarter",
            "values": [1, 1],
            "start_year": None,
            "end_year": None,
        },
    ]
    assert date_selection_from_json(payload) == parse_date_selection("@Q1,@Q2")


def test_an_empty_persisted_selection_is_the_empty_selection() -> None:
    assert date_selection_from_json([]) == ()


@pytest.mark.parametrize(
    "payload",
    [
        [{"kind": "quarter", "granularity": "quarter", "values": [1]}],
        [{"kind": "recurring", "granularity": "decade", "values": [1]}],
        [{"kind": "recurring", "granularity": "quarter", "values": []}],
        [{"kind": "recurring", "granularity": "quarter", "values": [5]}],
        [{"kind": "recurring", "granularity": "quarter", "values": ["1"]}],
        [{"kind": "absolute", "start_date": "not-a-date"}],
        [{"kind": "absolute", "start_date": 2024}],
        [
            {
                "kind": "recurring",
                "granularity": "quarter",
                "values": [1],
                "start_year": "1999",
            }
        ],
        ["not-an-object"],
    ],
)
def test_a_malformed_persisted_selection_is_rejected(payload: list[object]) -> None:
    with pytest.raises(ValueError):
        date_selection_from_json(payload)


def test_a_persisted_selection_is_validated_on_construction() -> None:
    """Deserialization is a construction path, so the dataclass checks bounds."""
    with pytest.raises(ValueError, match="starts after it ends"):
        AbsoluteDateClause(date(2024, 12, 31), date(2024, 1, 1))
    with pytest.raises(ValueError, match="starts after it ends"):
        RecurringDateClause("quarter", (1,), 2015, 2011)
    with pytest.raises(ValueError, match="must name at least one period"):
        RecurringDateClause("quarter", (), None, None)
    with pytest.raises(ValueError, match="is outside 1..4"):
        RecurringDateClause("quarter", (5,), None, None)
    with pytest.raises(ValueError, match="is outside 1..12"):
        RecurringDateClause("month", (13,), None, None)
    with pytest.raises(ValueError, match="granularity must be one of"):
        RecurringDateClause("decade", (1,), None, None)
