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
