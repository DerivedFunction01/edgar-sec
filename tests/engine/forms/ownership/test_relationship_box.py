"""Tests for the ownership relationship box token stream."""

from __future__ import annotations

from edgar_sec.engine.forms.ownership.relationship_box import parse_relationship_box


def _rows(*rows: tuple[str, ...]) -> list[tuple[str, ...]]:
    return list(rows)


def test_marks_pair_with_the_label_that_follows_them() -> None:
    rows = _rows(
        (
            "1. Name and Address of Reporting Person",
            "2. Issuer Name",
            "",
            "6. Relationship of Reporting Person(s) to Issuer",
        ),
        ("Director", "10% Owner", ""),
        ("X", "Officer (give title below)", "", "Other (specify below)"),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.roles == {
        "director": False,
        "officer": True,
        "ten_percent": False,
        "other": False,
    }


def test_a_checked_mark_binds_the_next_label_not_the_previous_one() -> None:
    rows = _rows(
        ("6. Relationship of Reporting Person(s) to Issuer",),
        ("Officer (give title below)", "X", "Other (specify below)"),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.roles["other"] is True
    assert box.roles["officer"] is False
    assert box.other_text is None
    assert box.officer_title is None


def test_underscore_marks_are_recognised_next_to_their_label() -> None:
    rows = _rows(
        ("6. Relationship of Reporting Person(s) to Issuer",),
        ("__X___Director", "", "_____ 10% Owner"),
        ("__X___Officer (give", "", "_____ Other (specify below)"),
        ("title below)", "", "President, CEO, and Director"),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.roles["director"] is True
    assert box.roles["officer"] is True
    assert box.officer_title == "President, CEO, and Director"


def test_free_text_below_the_box_is_the_officer_title() -> None:
    rows = _rows(
        ("6. Relationship of Reporting Person(s) to Issuer",),
        ("X", "Director", "", "10% Owner"),
        ("X", "Officer (give title below)", "", "Other (specify below)"),
        ("President - Example Japan",),
        ("7. Individual or Joint/Group Filing",),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.officer_title == "President - Example Japan"


def test_free_text_below_a_checked_other_box_is_the_other_description() -> None:
    rows = _rows(
        ("6. Relationship of Reporting Person(s) to Issuer",),
        ("Director", "", "10% Owner"),
        ("Officer (give title below)", "X", "Other (specify below)"),
        ("Former Chief Financial Officer",),
        ("7. Individual or Joint/Group Filing",),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.roles["other"] is True
    assert box.other_text == "Former Chief Financial Officer"
    assert box.officer_title is None


def test_prose_relationship_box_binds_marks_in_reading_order() -> None:
    rows = _rows(
        (
            "6. Relationship of Reporting Person(s) to Issuer (Check all applicable)",
            "Director 10% Owner",
            "X Officer Other",
            "Officer/Other Description Executive Officer",
            "7. Individual or Joint/Group Filing",
        ),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.roles["officer"] is True
    assert box.roles["director"] is False
    assert box.officer_title == "Executive Officer"


def test_equally_near_marks_leave_a_role_association_unresolved() -> None:
    rows = _rows(
        ("6. Relationship of Reporting Person(s) to Issuer",),
        ("X", "", "X"),
        ("", "Director", ""),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.roles["director"] is False


def test_a_box_without_a_relationship_header_is_not_resolved() -> None:
    assert parse_relationship_box([("1. Name and Address", "2. Issuer Name")]) is None


def test_the_next_box_number_does_not_join_the_officer_title() -> None:
    rows = _rows(
        (
            "6. Relationship of Reporting Person(s) to Issuer (Check all applicable)",
            "Director 10% Owner",
            "X Officer Other",
            "Officer/Other Description Corporate Vice President",
            "7. Individual or Joint/Group Filing (Check Applicable Line)",
        ),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.officer_title == "Corporate Vice President"


def test_a_role_word_inside_the_title_is_not_read_as_a_label() -> None:
    rows = _rows(
        (
            "6. Relationship of Reporting Person(s) to Issuer (Check all applicable)",
            "Director 10% Owner",
            "X Officer (give title below)",
            "X Other (specify below)",
            "EXECUTIVE VICE PRESIDENT and DIRECTOR EMERITUS",
        ),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.other_text == "EXECUTIVE VICE PRESIDENT and DIRECTOR EMERITUS"
    assert box.officer_title is None


def test_a_title_that_follows_the_labels_on_the_next_line_is_read() -> None:
    rows = _rows(
        (
            "6. Relationship of Reporting Person(s) to Issuer (Check all applicable)",
            "Director 10% Owner",
            "X Officer (give title below)",
            "Other (specify below)",
            "Vice President Animal Safety Sales & Marketing",
            "7. Individual or Joint/Group Filing (Check applicable line)",
        ),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.officer_title == "Vice President Animal Safety Sales & Marketing"


def test_a_wrapped_slot_label_leaves_the_title_clean() -> None:
    rows = _rows(
        (
            "6. Relationship of Reporting Person(s) to Issuer (Check all applicable)",
            "X Director 10% Owner",
            "X Officer (give X Other (specify",
            "title below) below)",
            "President",
        ),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.other_text == "President"


def test_a_bare_role_word_in_its_own_cell_names_the_role() -> None:
    rows = _rows(
        (
            "6. Relationship of Reporting Person(s) to Issuer (Check all applicable)",
            "[] Director",
            "[ ] 10% Owner",
            "[x ] Officer",
            "(title) Executive Vice President & Treasurer/CFO",
            "[ ] Other",
            "(specify)",
        ),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.roles["officer"] is True
    assert box.officer_title == "Executive Vice President & Treasurer/CFO"


def test_the_value_is_read_from_the_slot_of_the_checked_role() -> None:
    rows = _rows(
        (
            "6. Relationship of Reporting Person(s) to Issuer (Check all applicable)",
            "X Officer",
            "Vice President",
            "[ ] Other",
            "(specify)",
        ),
    )

    box = parse_relationship_box(rows)

    assert box is not None
    assert box.officer_title == "Vice President"
