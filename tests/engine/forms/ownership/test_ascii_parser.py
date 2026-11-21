"""Tests for ASCII ownership top-level parser orchestrator."""

from edgar_sec.engine.forms.ownership.ascii_parser import parse_ascii_ownership

_FORM4_TEXT = (
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


def test_parse_ascii_ownership_form4_end_to_end() -> None:
    secs = parse_ascii_ownership(_FORM4_TEXT, "4")
    assert secs is not None
    assert secs.boxes_1_to_7 is not None
    assert secs.table_i is not None
    assert secs.signatures is not None


def test_parse_ascii_ownership_rejects_other_family() -> None:
    assert parse_ascii_ownership(_FORM4_TEXT, "3") is None
    assert parse_ascii_ownership(_FORM4_TEXT, "5") is None


def test_parse_ascii_ownership_form3_end_to_end() -> None:
    text = (
        "<DOCUMENT>\n<TYPE>3\n<SEQUENCE>1\n<FILENAME>fm3.txt\n<TEXT>\n"
        "1. Name and Address of Reporting Person\n"
        "Fogleman, Ronald R.\n"
        "1100 N. Wood Dale Road\n"
        "Wood Dale, IL 60191-\n"
        "2. Date of Event Requiring Statement (Month/Day/Year)\n"
        "07/11/2001\n"
        "4. Issuer Name and Ticker or Trading Symbol\n"
        "AAR CORP. (AIR)\n"
        "5. Relationship of Reporting Person(s) to Issuer (Check all applicable)\n"
        "(X) Director                   ( ) 10% Owner\n"
        "<TABLE>\n"
        "TABLE I -- Non-Derivative Securities Beneficially Owned\n"
        "<CAPTION>\n"
        "<S>                                         <C>                    <C>\n"
        "Common Stock                                0                      D\n"
        "</TABLE>\n"
        "SIGNATURE OF REPORTING PERSON\n"
        "/s/ Ronald R. Fogleman\n"
        "DATE\n"
        "07/20/2001\n"
        "</TEXT>\n</DOCUMENT>\n"
    )
    secs = parse_ascii_ownership(text, "3")
    assert secs is not None
    assert secs.boxes_1_to_7 is not None
    assert secs.signatures is not None


def test_parse_ascii_ownership_form5_end_to_end() -> None:
    text = (
        "FORM 5\n"
        "ANNUAL STATEMENT OF CHANGES IN BENEFICIAL OWNERSHIP\n"
        "1. Name and Address of Reporting Person*\n"
        "Hooks, Stephen V.\n"
        "3400 North Wolf Road\n"
        "Franklin Park, IL 60131\n"
        "2. Issuer Name and Ticker or Trading Symbol\n"
        "ACME CORP (ACM)\n"
        "4. Statement for Month/Day/Year\n"
        "12/31/2001\n"
        "6. Relationship of Reporting Person\n"
        "[X] Officer\n"
        "/s/ Stephen V. Hooks   02-03-2002\n"
    )
    secs = parse_ascii_ownership(text, "5")
    assert secs is not None
    assert secs.boxes_1_to_7 is not None
    assert secs.signatures is not None
