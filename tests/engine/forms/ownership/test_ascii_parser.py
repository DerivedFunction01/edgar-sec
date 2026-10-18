"""Tests for ASCII Form 4 top-level parser orchestrator."""

from edgar_sec.engine.forms.ownership.ascii_parser import parse_ascii_form4


def test_parse_ascii_form4_end_to_end() -> None:
    text = (
        "FORM 4\n"
        "1. Name and Address of Reporting Person*\n"
        "Hooks, Stephen V.\n"
        "3400 North Wolf Road\n"
        "Franklin Park, IL 60131\n"
        "2. Issuer Name and Ticker or Trading Symbol\n"
        "ACME CORP (ACM)\n"
        "4. Statement for Month/Day/Year\n"
        "06/01/2001\n"
        "6. Relationship of Reporting Person\n"
        "[X] Officer\n"
        "<TABLE>\n"
        "<CAPTION>\n"
        "Table I - Non-Derivative Securities\n"
        "<S>              <C>          <C>    <C>      <C>      <C>    <C>\n"
        "1. Title         2. Date      3.Code 4.Amount 5.Owned  6.Form 7.Nature\n"
        "Common Stock     06/01/2001   P      500 A    500      D\n"
        "</TABLE>\n"
        "/s/ Stephen V. Hooks   07-03-2001\n"
    )
    secs = parse_ascii_form4(text)
    assert secs is not None
    assert secs.boxes_1_to_7 is not None
    assert secs.table_i is not None
    assert secs.signatures is not None
