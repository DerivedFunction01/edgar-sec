from edgar_sec.engine.forms.ownership.reporting_owner_parser import (
    parse_reporting_owner,
)


def test_reporting_owner_parser_maps_foreign_jurisdiction_to_country() -> None:
    owner = parse_reporting_owner(
        "Reporting Person Jane Doe\n123 Main Street, Toronto, Ontario, Canada",
        "",
    )

    assert owner.street == "123 Main Street"
    assert owner.city == "Toronto"
    assert owner.country == "A6"
    assert owner.state is None


def test_reporting_owner_parser_resolves_a_filled_mark() -> None:
    owner = parse_reporting_owner(
        "Reporting Person Jane Doe",
        "___X____Director",
    )

    assert owner.is_director is True
    assert owner.is_officer is False


def test_reporting_owner_parser_resolves_a_lowercase_filled_mark() -> None:
    owner = parse_reporting_owner(
        "Reporting Person Jane Doe",
        "___x____Officer",
    )

    assert owner.is_officer is True
    assert owner.is_director is False


def test_reporting_owner_parser_ignores_an_unfilled_slot() -> None:
    owner = parse_reporting_owner(
        "Reporting Person Jane Doe",
        "________ Director",
    )

    assert owner.is_director is False
    assert owner.is_officer is False


def test_reporting_owner_parser_reads_a_shared_checked_glyph() -> None:
    owner = parse_reporting_owner(
        "Reporting Person Jane Doe",
        "✘ Director",
    )

    assert owner.is_director is True


def test_reporting_owner_parser_reads_a_checked_entity() -> None:
    owner = parse_reporting_owner(
        "Reporting Person Jane Doe",
        "&#9746; Director",
    )

    assert owner.is_director is True


def test_reporting_owner_parser_keeps_a_long_officer_title() -> None:
    owner = parse_reporting_owner(
        "Reporting Person Jane Doe",
        "X Officer (give title below) Executive Vice President, Office of the "
        "Chairman and Chief Technology Officer",
    )

    assert owner.is_officer is True
    assert owner.officer_title == (
        "Executive Vice President, Office of the Chairman and Chief Technology Officer"
    )


def test_reporting_owner_parser_reads_a_title_on_the_label_line() -> None:
    owner = parse_reporting_owner(
        "Reporting Person Jane Doe",
        "X (Officer, give title below) Executive Vice President",
    )

    assert owner.is_officer is True
    assert owner.officer_title == "Executive Vice President"
