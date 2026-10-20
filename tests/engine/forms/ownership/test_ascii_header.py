"""Tests for ASCII Form 4 header and signature extraction."""

from edgar_sec.engine.forms.ownership.ascii_header import (
    extract_ascii_header_and_signatures,
)
from edgar_sec.engine.forms.ownership.metadata_parser import parse_metadata


def test_extract_ascii_header_columns() -> None:
    text = (
        "1. Name and Address of Reporting Person*\n"
        "Smith, John\n"
        "100 Main St\n"
        "Boston, MA 02110\n"
        "2. Issuer Name and Ticker or Trading Symbol\n"
        "ACME CORP (ACM)\n"
        "4. Statement for Month/Day/Year\n"
        "05/15/2002\n"
        "6. Relationship of Reporting Person\n"
        "[X] Director\n"
        "TABLE I - NON-DERIVATIVE SECURITIES\n"
        "/s/ John Smith   05/15/2002\n"
    )
    boxes, sigs = extract_ascii_header_and_signatures(text)
    assert boxes is not None
    meta = parse_metadata(boxes, sigs)
    assert meta.issuer.name == "ACME CORP"
    assert meta.issuer.trading_symbol == "ACM"
    assert meta.reporting_owner.is_director is True
    assert meta.period.period_of_report == "2002-05-15"


def test_extract_ascii_header_pipe_table() -> None:
    text = (
        "|1. Name and Address of Report-  |2. Issuer Name and Ticker or Trading Symbol  |\n"
        "|    ing Person*                 |                                             |\n"
        "| Wilpon Fred ---                | Loews Corporation (LTR)                     |\n"
        "|--------------------------------|---------------------------------------------|\n"
        "|4. Statement for Month/Day/Year |6. Relationship of Reporting Person          |\n"
        "| 1/2/03                         | [X] Director                                |\n"
        "TABLE I - NON-DERIVATIVE SECURITIES\n"
        "/s/ Fred Wilpon   1/2/03\n"
    )
    boxes, sigs = extract_ascii_header_and_signatures(text)
    assert boxes is not None
    meta = parse_metadata(boxes, sigs)
    assert meta.issuer.name == "Loews Corporation"
    assert meta.issuer.trading_symbol == "LTR"
    assert meta.reporting_owner.is_director is True


def test_extract_ascii_header_with_checkboxes() -> None:
    text = (
        "|_| Check this box if no longer subject to Section 16.\n"
        "1.   Name and Address of Reporting Person*\n"
        "Mao, Shing\n"
        "(Last) (First) (Middle)\n"
        "3050 East Hillcrest Drive\n"
        "(Street)\n"
        "Westlake Village, CA 91362\n"
        "(City) (State) (Zip)\n"
        "2.   Issuer Name and Ticker or Trading Symbol\n"
        "Diodes Incorporated (DIOD)\n"
        "4.   Statement for Month/Day/Year\n"
        "March 14, 2003\n"
        "6.   Relationship of Reporting Person(s) to Issuer\n"
        "|X| Director\n"
        "|_| Officer (give title below)\n"
        "TABLE I - NON-DERIVATIVE SECURITIES\n"
        "/s/ Shing Mao   03/14/2003\n"
    )
    boxes, sigs = extract_ascii_header_and_signatures(text)
    assert boxes is not None
    meta = parse_metadata(boxes, sigs)
    assert meta.issuer.name == "Diodes Incorporated"
    assert meta.issuer.trading_symbol == "DIOD"
    assert meta.reporting_owner.name == "Mao, Shing"
    assert meta.reporting_owner.is_director is True
