"""Tests for columnar signature and notice-date extraction."""

from edgar_sec.engine.forms.common.columnar_signatures import (
    extract_columnar_signature_and_date,
)


def test_columnar_finds_conformed_name_and_notice_date() -> None:
    lines = [
        "Explanation of Responses:",
        "/s/ Jane Q Roe",
        "Date of Notice: 03/04/2003",
    ]
    name, date = extract_columnar_signature_and_date(lines, reference_year=2003)
    assert name == "Jane Q Roe"
    assert date == "03/04/2003"


def test_columnar_ignores_boilerplate_and_as_of_dates() -> None:
    lines = [
        "** Intentional misstatements or omissions of facts constitute",
        "Federal Criminal Violations. See 18 U.S.C. 1001 and 15 U.S.C. 78ff(a).",
        "Date of Notice: as of December 31, 2002",
    ]
    name, date = extract_columnar_signature_and_date(lines, reference_year=2002)
    assert name is None
    assert date is None
