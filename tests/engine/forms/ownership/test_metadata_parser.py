"""Tests for Form 4 metadata and Box 1 to 7 extraction."""

from edgar_sec.engine.forms.ownership.metadata_parser import parse_metadata
from edgar_sec.engine.forms.ownership.sections import partition_ownership_tables

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
    sections = partition_ownership_tables(SAMPLE_BOXES_HTML)
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

    assert meta.period.period_of_report == "2001-06-01"
    assert meta.period.is_amendment is False

    assert meta.signature_name == "Stephen V. Hooks"
    assert meta.signature_date == "2001-07-03"


def test_parse_metadata_associates_font_checkbox_with_adjacent_role_cell() -> None:
    html = """<html><body><table><tr>
      <td>1. Name and Address of Reporting Person Jane Doe</td>
      <td>6. Relationship of Reporting Person(s) to Issuer</td>
    </tr><tr>
      <td><font face="Wingdings">&#120;</font></td><td>Director</td>
      <td><font face="Webdings">&#111;</font></td><td>10% Owner</td>
    </tr></table></body></html>"""
    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)
    assert meta.reporting_owner.is_director is True
    assert meta.reporting_owner.is_ten_percent_owner is False


def test_parse_metadata_joins_fragmented_box_fields() -> None:
    html = """<html><body>
    <table><tr><td>FORM 4</td></tr></table>
    <table><tr><td>(Last)</td><td>Graham, Jr.</td></tr>
    <tr><td>(First)</td><td>William</td></tr>
    <tr><td>(Middle)</td><td>A.</td></tr>
    <tr><td>(Street)</td><td>2301 Maysville Road</td></tr>
    <tr><td>(City)</td><td>Flemingsburg</td></tr>
    <tr><td>(State)</td><td>KY</td></tr>
    <tr><td>(Zip)</td><td>41041-8136</td></tr></table>
    <table><tr><td>(Issuer Name)</td><td>Community Trust Bancorp, Inc.</td></tr>
    <tr><td>(Ticker or Trading Symbol)</td><td>CTBI</td></tr></table>
    <table><tr><td>(I.D. Number)</td></tr></table>
    <table><tr><td>(Month/Day)</td><td>February 26</td></tr>
    <tr><td>(Year)</td><td>2003</td></tr></table>
    <table><tr><td>(Month/Day)</td><td></td></tr>
    <tr><td>(Year)</td><td></td></tr></table>
    <table><tr><td>X</td><td>(Director) (Officer) (10% Owner) (Other)</td></tr></table>
    <table><tr><td>X</td><td>Form filed by One Reporting Person</td></tr></table>
    <table><tr><td>Table I - Non-Derivative Securities</td></tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)
    owner = meta.reporting_owner

    assert owner.name == "Graham, Jr., William A."
    assert owner.street == "2301 Maysville Road"
    assert owner.city == "Flemingsburg"
    assert owner.state == "KY"
    assert owner.zip_code == "41041-8136"
    assert owner.is_director is True
    assert owner.is_ten_percent_owner is False
    assert meta.issuer.name == "Community Trust Bancorp, Inc."
    assert meta.issuer.trading_symbol == "CTBI"
    assert meta.period.period_of_report == "2003-02-26"
    assert sections.unparsed == []


def test_parse_metadata_does_not_use_amendment_date_as_period() -> None:
    html = """<html><body>
    <table><tr><td>(Month/Day)</td><td></td></tr>
    <tr><td>(Year)</td><td></td></tr></table>
    <table><tr><td>(Month/Day)</td><td>February 26</td></tr>
    <tr><td>(Year)</td><td>2003</td></tr></table>
    <table><tr><td>Table I - Non-Derivative Securities</td></tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)
    assert meta.period.period_of_report is None


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
    sections = partition_ownership_tables(STACKED_BOXES_HTML)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.issuer.name == "InterDigital Communications Corporation"
    assert meta.issuer.trading_symbol == "IDCC"
    assert meta.reporting_owner.name == "Merritt, William J."
    assert meta.period.period_of_report == "2003-02-19"
    assert meta.signature_name == "Louis E. Stellato"
    assert meta.signature_date == "2003-02-04"


def test_parse_metadata_rejects_omb_and_statutory_boilerplate() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person*\nJane Doe</td></tr></table>
    <table><tr>
      <td>** Intentional misstatements or omissions of facts constitute Federal Criminal Violations.</td>
      <td>m displays a currently valid OMB number\n**Signature of Reporting Person</td>
      <td>10/15/2026</td>
    </tr></table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)
    assert meta.signature_name is None
    assert meta.signature_date == "2026-10-15"


def test_parse_metadata_handles_reporting_person_plural_and_by_signature() -> None:
    html = """<html><body>
    <table><tr>
      <td>1. Name and Address of Reporting Person(s)<br>Hayes, John A.</td>
      <td>6. Relationship of Reporting Person(s) to Issuer (Check all applicable)<br>[X] Officer</td>
    </tr></table>
    <table><tr><td>**Signature of Reporting Person</td><td>Date</td></tr>
    <tr><td>By: Patricia A. Bell<br>For: John A. Hayes</td><td>04/25/03</td></tr></table>
    </body></html>"""

    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.reporting_owner.name == "Hayes, John A."
    assert meta.signature_name == "Patricia A. Bell"
    assert meta.signature_date == "04/25/03"


def test_parse_metadata_retains_long_entity_reporting_owner_name() -> None:
    owner = (
        "Administrative Committee of the Modine Manufacturing Company "
        "Employee Stock Ownership & Investment Plans (ESOPs)"
    )
    html = f"""<html><body><table><tr><td>
    1. Name and Address of Reporting Person<br>{owner}<br>
    1500 DeKoven Avenue<br>Racine, WI 53403
    </td></tr></table></body></html>"""

    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.reporting_owner.name == owner


def test_parse_metadata_extracts_signer_before_power_of_attorney_title() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person<br>Jane Doe</td></tr></table>
    <table><tr><td>Signature of Reporting Person</td><td>Date</td></tr>
    <tr><td>By: W. Edwin Frazier, III, Attorney-in-Fact</td><td>02/14/03</td></tr></table>
    </body></html>"""

    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.signature_name == "W. Edwin Frazier, III"


def test_parse_metadata_extracts_signer_before_poa_parenthetical() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person<br>Jane Doe</td></tr></table>
    <table><tr><td>Signature of Reporting Person</td><td>Date</td></tr>
    <tr><td>By: James B. Benson (POA on file) _______</td><td>02/14/03</td></tr></table>
    </body></html>"""

    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.signature_name == "James B. Benson"


def test_parse_metadata_handles_repeated_by_and_dash_poa_suffix() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person<br>Jane Doe</td></tr></table>
    <table><tr><td>Signature of Reporting Person</td><td>Date</td></tr>
    <tr><td>By: By Robin A. Stoner - Attorney-in-Fact</td><td>02/14/03</td></tr></table>
    </body></html>"""

    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.signature_name == "Robin A. Stoner"


def test_parse_metadata_extracts_name_preceding_power_of_attorney_role() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person<br>Kenneth A. Jacob</td></tr></table>
    <table><tr><td>________<br>** Signature of Reporting Person Date<br>
    Tammy Eng-Palmer, Power of Attorney<br>Kenneth A. Jacob</td></tr></table>
    </body></html>"""

    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.signature_name == "Tammy Eng-Palmer"


def test_parse_metadata_extracts_conformed_signer_before_underline() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person<br>Jane Doe</td></tr></table>
    <table><tr><td>/s/ Hugh L. Carey__________ ** Signature of Reporting Person Date</td></tr></table>
    </body></html>"""

    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.signature_name == "Hugh L. Carey"


def test_parse_metadata_preserves_curly_apostrophe_in_signer_name() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person<br>Jane Doe</td></tr></table>
    <table><tr><td>/s/ Stonie R. O’Briant________________ ** Signature of Reporting Person Date</td></tr></table>
    </body></html>"""

    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.signature_name == "Stonie R. O’Briant"


def test_parse_metadata_extracts_underlined_signer_before_signature_label() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person<br>Lloyd D. Ward</td></tr></table>
    <table><tr><td>____Anthony J. Horan__________ ___January 2, 2003________<br>
    ** Signature of Reporting Person Date<br>On behalf of Lloyd D. Ward</td></tr></table>
    </body></html>"""

    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert meta.signature_name == "Anthony J. Horan"


def test_parse_metadata_extracts_signature_outside_tables() -> None:
    html = """<html><body>
    <table><tr><td>1. Name and Address of Reporting Person<br>John A. Hayes</td></tr></table>
    <p>SIGNATURE OF REPORTING<br>PERSON<br>/S/&nbsp;&nbsp;By:&nbsp;&nbsp;Mary L. Rose, Dir., Exec. Comp. Prog.</p>
    <p>For:&nbsp;&nbsp;John A. Hayes</p>
    <p>DATE&nbsp;&nbsp;04/28/03</p>
    </body></html>"""

    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)

    assert sections.signatures is not None
    assert meta.signature_name == "Mary L. Rose"
    assert meta.signature_date == "04/28/03"


def test_parse_metadata_excludes_statutory_boilerplate_from_owner_name() -> None:
    """Verify statutory boilerplate in row[:2] is rejected from candidate owner lines."""
    html = """<html><body>
    <table>
      <tr><td>Filed pursuant to Section 16(a) of the Securities Exchange Act of 1934</td><td>2. Issuer Name: Acme Corp</td></tr>
      <tr><td>Check this box if no longer subject to Section 16</td><td>3. IRS: 12-3456789</td></tr>
      <tr><td>1. Name and Address of Reporting Person</td><td>4. Statement for 01/15/2003</td></tr>
      <tr><td>Jane Smith</td><td></td></tr>
      <tr><td>100 Main St</td><td></td></tr>
      <tr><td>Boston, MA 02110</td><td></td></tr>
    </table>
    </body></html>"""
    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)
    assert meta.reporting_owner.name == "Jane Smith"
    assert "Section 16" not in (meta.reporting_owner.name or "")


def test_parse_metadata_same_row_right_cell_period() -> None:
    """Verify period date located on the same row to the right is extracted."""
    html = """<html><body><table>
      <tr><td>1. Name: Jane Smith</td><td>2. Issuer: Acme ACM</td></tr>
      <tr><td>4.</td><td>Statement for Month/Year</td><td>April, 2001</td></tr>
    </table></body></html>"""
    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)
    assert meta.period.period_of_report == "2001-04-01"


def test_parse_metadata_vertical_lookahead_skips_intervening_address() -> None:
    """Verify vertical lookahead does not get trapped by non-date address numbers."""
    html = """<html><body><table>
      <tr><td>Jane Smith</td><td>4. Statement for Month/Day/Year</td></tr>
      <tr><td>5 East Greenway Plaza</td><td></td></tr>
      <tr><td>Houston, TX 77046</td><td>07/17/2002</td></tr>
    </table></body></html>"""
    sections = partition_ownership_tables(html)
    meta = parse_metadata(sections.boxes_1_to_7, sections.signatures)
    assert meta.period.period_of_report == "2002-07-17"
