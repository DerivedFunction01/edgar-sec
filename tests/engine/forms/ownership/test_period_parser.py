from edgar_sec.engine.forms.ownership.period_parser import parse_period


def test_period_parser_prefers_date_line_over_numbered_label() -> None:
    combined = (
        "1. 1. Name and Address of Reporting Person\n"
        "Fogleman, Ronald R.\n"
        "2. Date of Event Requiring Statement (Month/Day/Year)\n"
        "07/11/2001"
    )
    result = parse_period(combined)
    assert result.period_of_report == "07/11/2001"


def test_period_parser_reads_date_glued_to_amendment_label() -> None:
    result = parse_period("5. If Amendment, Date of Original (Month/Year) 2/27/03")
    assert result.is_amendment is True
    assert result.date_of_original == "2/27/03"
    assert result.period_of_report == "2/27/03"


def test_period_parser_recognizes_period_and_amendment_dates() -> None:
    original = parse_period(
        "4. Statement for\nMonth/Day/Year\n12/31/02\n5. If Amendment,\nDate of Original\n(Month/Day/Year)"
    )
    assert original.period_of_report == "12/31/02"
    assert original.is_amendment is False
    assert original.date_of_original is None

    amendment = parse_period(
        "4. Statement for Month/Day/Year\n02/19/2003\n5. If Amendment, Date of Original (Month/Day/Year)\n01/15/2003"
    )
    assert amendment.period_of_report == "02/19/2003"
    assert amendment.is_amendment is True
    assert amendment.date_of_original == "01/15/2003"
