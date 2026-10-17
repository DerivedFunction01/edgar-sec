"""Tests for Form 144 cover-box extraction."""

from edgar_sec.engine.forms.form144.cover_parser import parse_cover_box_1_2
from edgar_sec.engine.forms.form144.sections import partition_form144_tables


def test_parse_cover_issuer_and_reporting_person():
    html = """
    <table>
      <tr><td>1 (a) NAME OF ISSUER</td><td>Acme Corp</td>
          <td>(b) IRS IDENT. NO.</td><td>12-3456789</td>
          <td>(c) S.E.C. FILE NO.</td><td>001-12345</td></tr>
      <tr><td>1 (d) ADDRESS OF ISSUER</td>
          <td colspan="5">100 Main St, New York, NY 10001
          (e) TELEPHONE NO. (212) 555-0100</td></tr>
      <tr><td>2 (a) NAME OF PERSON FOR WHOSE ACCOUNT SOLD</td><td>Jane Doe</td>
          <td>(b) RELATIONSHIP TO ISSUER</td><td colspan="3">Officer</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    issuer, seller = parse_cover_box_1_2(sections.cover_box_1_2)
    assert issuer.name == "Acme Corp"
    assert issuer.sec_file_number == "001-12345"
    assert seller.name == "Jane Doe"
    assert "Officer" in seller.relationships


def test_parse_split_cover_tables_and_same_cell_values():
    html = """
    <table>
      <tr><td>1 (a) NAME OF ISSUER (Please type or print)<br>Allegion plc</td>
          <td>(b) IRS IDENT. NO.<br>98-1108930</td>
          <td>(c) S.E.C. FILE NO.<br>001-35971</td></tr>
    </table>
    <table>
      <tr><td>1 (d) ADDRESS OF ISSUER</td><td>STREET</td><td>CITY</td>
          <td>STATE</td><td>ZIP CODE</td><td>(e) TELEPHONE NO.</td></tr>
      <tr><td></td><td>11819 N. Pennsylvania Street</td><td>Carmel</td>
          <td>IN</td><td>46032</td><td>AREA CODE 317 NUMBER 810-3700</td></tr>
    </table>
    <table>
      <tr><td>2 (a) NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES ARE TO BE SOLD<br>
          Feng “William” Yu</td><td>(b) RELATIONSHIP TO ISSUER<br>Officer</td>
          <td>(c) ADDRESS STREET CITY STATE ZIP CODE<br>
          c/o Schlage Lock Company, LLC<br>
          11819 N. Pennsylvania Street, Carmel, IN 46032</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    issuer, seller = parse_cover_box_1_2(sections.cover_box_1_2)
    assert issuer.name == "Allegion plc"
    assert issuer.sec_file_number == "001-35971"
    assert issuer.street1 == "11819 N. Pennsylvania Street"
    assert issuer.city == "Carmel"
    assert issuer.state_or_country == "IN"
    assert issuer.zip_code == "46032"
    assert issuer.contact_phone == "317 810-3700"
    assert seller.name == "Feng “William” Yu"
    assert seller.city == "Carmel"
    assert seller.state_or_country == "IN"
    assert seller.zip_code == "46032"
    assert "Officer" in seller.relationships


def test_parse_inline_address_columns_and_split_name_lines():
    html = """
    <table>
      <tr><td>1 (a) NAME OF ISSUER<br>Royce Micro-Cap Trust, Inc.</td></tr>
      <tr><td>1 (d) ADDRESS OF ISSUER</td><td>STREET<br>745 Fifth Avenue</td>
          <td>CITY<br>New York</td><td>STATE<br>NY</td><td>10151</td></tr>
      <tr><td>2 (a) NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES ARE TO BE SOLD<br>
          Charles<br>M. Royce*</td><td>RELATIONSHIP TO ISSUER<br>Director</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    issuer, seller = parse_cover_box_1_2(sections.cover_box_1_2)
    assert issuer.name == "Royce Micro-Cap Trust, Inc."
    assert issuer.street1 == "745 Fifth Avenue"
    assert issuer.city == "New York"
    assert issuer.state_or_country == "NY"
    assert issuer.zip_code == "10151"
    assert seller.name == "Charles M. Royce*"


def test_parse_owner_name_from_adjacent_value_row():
    html = """
    <table>
      <tr><td>1 (a) NAME OF ISSUER</td><td>Acme Corp</td></tr>
    </table>
    <table>
      <tr><td>2 (a)</td>
          <td>NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES ARE TO BE SOLD</td>
          <td>RELATIONSHIP TO ISSUER</td></tr>
      <tr><td>James C. Schmitz</td><td></td><td>Director</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    _, seller = parse_cover_box_1_2(sections.cover_box_1_2)
    assert seller.name == "James C. Schmitz"
    assert "Director" in seller.relationships


def test_parse_cover_form_label_continuation_and_full_state_address():
    html = """
    <table><tr><td>1 (a) NAME OF ISSUER</td><td>Valhi, Inc.</td></tr></table>
    <table><tr><td>2 (a) NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES
        RELATIONSHIP TO ISSUER<br>ARE TO BE SOLD<br>
        Harold Simmons Foundation, Inc. Affiliate</td></tr></table>
    <table><tr><td>(c) ADDRESS STREET CITY STATE ZIP CODE</td></tr>
        <tr><td>5430 LBJ Freeway, Suite 1700, Dallas, Texas 75019</td></tr></table>
    """
    sections = partition_form144_tables(html)
    assert sections.cover_box_1_2 is not None
    assert sections.unparsed == []
    _, seller = parse_cover_box_1_2(sections.cover_box_1_2)
    assert seller.name == "Harold Simmons Foundation, Inc."
    assert seller.street1 == "5430 LBJ Freeway, Suite 1700"
    assert seller.city == "Dallas"
    assert seller.state_or_country == "Texas"
    assert seller.zip_code == "75019"
    assert seller.relationships == ("Affiliate",)


def test_parse_populated_name_and_address_across_form_box_columns():
    html = """
    <table>
      <tr><td>1 (a) NAME OF ISSUER</td><td>Arkansas Best Corporation</td></tr>
      <tr><td>1 (d) ADDRESS OF ISSUER</td><td>STREET</td><td>CITY</td>
          <td>STATE</td><td>ZIP CODE</td></tr>
      <tr><td></td><td></td><td></td><td></td><td></td></tr>
      <tr><td></td><td></td><td></td><td></td><td></td></tr>
      <tr><td>3801 Old Greenwood Road</td><td></td><td>Fort Smith</td>
          <td>AR</td><td>72903</td></tr>
      <tr><td>2 (a) NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES ARE TO BE SOLD</td>
          <td>(b) IRS IDENT. NO.</td><td>(c) RELATIONSHIP TO ISSUER</td>
          <td>(d) ADDRESS</td><td>STREET</td><td>CITY</td><td>STATE</td>
          <td>ZIP CODE</td></tr>
      <tr><td>William A. Marquard</td><td></td><td>Former Director</td>
          <td>2199 Maysville Road</td><td></td><td>Carlisle</td><td>KY</td>
          <td>40311</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    issuer, seller = parse_cover_box_1_2(sections.cover_box_1_2)
    assert issuer.street1 == "3801 Old Greenwood Road"
    assert issuer.city == "Fort Smith"
    assert issuer.state_or_country == "AR"
    assert issuer.zip_code == "72903"
    assert seller.name == "William A. Marquard"
    assert seller.street1 == "2199 Maysville Road"
    assert seller.city == "Carlisle"
    assert seller.state_or_country == "KY"
    assert seller.zip_code == "40311"
