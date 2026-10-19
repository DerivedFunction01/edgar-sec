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
