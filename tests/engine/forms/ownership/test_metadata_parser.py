"""Tests for Form 4 metadata and Box 1 to 7 extraction."""

from edgar_sec.engine.forms.ownership.metadata_parser import parse_metadata
from edgar_sec.engine.forms.ownership.sections import partition_form4_tables

SAMPLE_BOXES_HTML = """
<html><body>
<table><tr>
  <td>1. Name and Address of Reporting Person* Hooks, Stephen V. (Last) (First) (Middle) 3400 North Wolf Road (Street) Franklin Park, IL 60131 (City) (State) (Zip)</td>
  <td>2. Issuer Name and Ticker or Trading Symbol\nA. M. Castle & Co. CAS\n3. I.R.S. Identification Number of Reporting Person 36-1234567</td>
  <td>4. Statement for (Month/Year)\nJune 2001\n5. If Amendment, Date of Original</td>
  <td>6. Relationship of Reporting Person(s) to Issuer\nDirector 10% Owner\nX Officer Other\nOfficer/Other Description Vice President</td>
</tr></table>
<table><tr>
  <td>** Signature of Reporting Person Date\nStephen V. Hooks\n07-03-2001</td>
</tr></table>
</body></html>
"""


def test_parse_metadata_extracts_owner_and_issuer() -> None:
    sections = partition_form4_tables(SAMPLE_BOXES_HTML)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.issuer.name == "A. M. Castle & Co."
    assert meta.issuer.trading_symbol == "CAS"
    assert meta.issuer.irs_number == "36-1234567"

    assert meta.reporting_owner.name == "Hooks, Stephen V."
    assert meta.reporting_owner.street == "3400 North Wolf Road"
    assert meta.reporting_owner.city == "Franklin Park"
    assert meta.reporting_owner.state == "IL"
    assert meta.reporting_owner.zip_code == "60131"
    assert meta.reporting_owner.is_officer is True
    assert meta.reporting_owner.is_director is False
    assert meta.reporting_owner.officer_title == "Vice President"

    assert meta.period.period_of_report == "June 2001"
    assert meta.period.is_amendment is False

    assert meta.signature_name == "Stephen V. Hooks"
    assert meta.signature_date == "07-03-2001"


STACKED_BOXES_HTML = """
<html><body>
<table>
  <tr>
    <td>1. Name and Address of Reporting Person*</td>
    <td>2. Issuer Name and Ticker or Trading Symbol</td>
    <td>4. Statement for (Month/Day/Year)</td>
  </tr>
  <tr>
    <td>Merritt, William J.</td>
    <td>InterDigital Communications Corporation (IDCC)</td>
    <td>02/19/2003</td>
  </tr>
</table>
<table>
  <tr>
    <td>By: /s/ Louis E. Stellato, Attorney-in-Fact\n**Signature of Reporting Person</td>
    <td>February 4, 2003\nDate</td>
  </tr>
</table>
</body></html>
"""


def test_parse_metadata_handles_stacked_2row_layout() -> None:
    sections = partition_form4_tables(STACKED_BOXES_HTML)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.issuer.name == "InterDigital Communications Corporation"
    assert meta.issuer.trading_symbol == "IDCC"
    assert meta.reporting_owner.name == "Merritt, William J."
    assert meta.period.period_of_report == "02/19/2003"
    assert meta.signature_name == "Louis E. Stellato"
    assert meta.signature_date == "February 4, 2003"


def test_parse_metadata_conformed_signatures_and_tickers() -> None:
    from edgar_sec.engine.forms.ownership.metadata_parser import _parse_issuer

    iss1 = _parse_issuer("Issuer Name: Macrovision Corporation (Nasdaq: MVSN)")
    assert iss1.name == "Macrovision Corporation"
    assert iss1.trading_symbol == "MVSN"

    iss2 = _parse_issuer(
        '2. Issuer Name and Ticker: Dendrite International Inc ("DRTE")'
    )
    assert iss2.name == "Dendrite International Inc"
    assert iss2.trading_symbol == "DRTE"

    iss3 = _parse_issuer("Issuer Name: Emerson Electric Co. - EMR")
    assert iss3.name == "Emerson Electric Co."
    assert iss3.trading_symbol == "EMR"

    iss4 = _parse_issuer(
        "2. Issuer Name and Ticker or Trading Symbol\nSizeler Property Investors, Inc.\nSIZ"
    )
    assert iss4.name == "Sizeler Property Investors, Inc."
    assert iss4.trading_symbol == "SIZ"

    iss5 = _parse_issuer(
        "2. Issuer Name and Ticker or Trading Symbol\nThe Neiman Marcus Group, Inc.\n(NMG.A and NMG.B)"
    )
    assert iss5.name == "The Neiman Marcus Group, Inc."
    assert iss5.trading_symbol == "NMG.A"


def test_parse_period_and_amendments() -> None:
    from edgar_sec.engine.forms.ownership.metadata_parser import _parse_period

    p1 = _parse_period(
        "4. Statement for\nMonth/Day/Year\n12/31/02\n5. If Amendment,\nDate of Original\n(Month/Day/Year)"
    )
    assert p1.period_of_report == "12/31/02"
    assert p1.is_amendment is False
    assert p1.date_of_original is None

    p2 = _parse_period(
        "4. Statement for Month/Day/Year\n02/19/2003\n5. If Amendment, Date of Original (Month/Day/Year)\n01/15/2003"
    )
    assert p2.period_of_report == "02/19/2003"
    assert p2.is_amendment is True
    assert p2.date_of_original == "01/15/2003"
