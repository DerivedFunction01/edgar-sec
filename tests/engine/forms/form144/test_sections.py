"""Tests for Form 144 HTML section partitioning."""

from edgar_sec.engine.forms.form144.sections import (
    SectionRole,
    partition_form144_tables,
)
from edgar_sec.engine.forms.form144.securities import parse_table_ii_rows

SAMPLE_HTML = """
<html><body>
<table><tr><td>UNITED STATES SECURITIES AND EXCHANGE COMMISSION FORM 144</td></tr>
<tr><td>1 (a) NAME OF ISSUER Acme Corp (b) IRS IDENT. NO. 12-3456789</td></tr>
<tr><td>2 (a) NAME OF PERSON FOR WHOSE ACCOUNT SOLD Jane Doe (b) RELATIONSHIP TO ISSUER Officer</td></tr>
</table>
<table><tr><td>3 (a) Title of the Class Common Stock (b) Name and Address of Each Broker Merrill Lynch</td></tr>
<tr><td>Number of Shares To Be Sold 5,000 Aggregate Market Value $100,000.00</td></tr>
</table>
<table><tr><td>TABLE I - SECURITIES TO BE SOLD</td></tr>
<tr><td>Title of the Class</td><td>Date you Acquired</td><td>Nature of Acquisition Transaction</td><td>Amount Acquired</td></tr>
<tr><td>Common Stock</td><td>01/15/2020</td><td>RSU Vest</td><td>5,000</td></tr>
</table>
<table><tr><td>TABLE II - SECURITIES SOLD DURING THE PAST 3 MONTHS</td></tr>
<tr><td>None</td></tr>
</table>
<table><tr><td>/s/ Jane Doe DATE OF NOTICE: 05/10/2022</td></tr></table>
</body></html>
"""


def test_partition_form144_sections():
    sections = partition_form144_tables(SAMPLE_HTML)
    assert sections.cover_box_1_2 is not None
    assert sections.cover_box_1_2.role == SectionRole.COVER_BOX_1_2
    assert sections.proposed_sale_box_3 is not None
    assert sections.proposed_sale_box_3.role == SectionRole.PROPOSED_SALE_BOX_3
    assert sections.table_i is not None
    assert sections.table_i.role == SectionRole.TABLE_I
    assert sections.table_ii is not None
    assert sections.table_ii.role == SectionRole.TABLE_II
    assert len(sections.signatures) >= 1


def test_instruction_language_does_not_hide_populated_cover():
    html = """
    <table>
      <tr><td>ATTENTION: Transmit for filing 3 copies of this form.</td></tr>
      <tr><td>1 (a) NAME OF ISSUER</td><td>Acme Corp</td></tr>
      <tr><td>(b) IRS IDENT. NO.</td><td>12-3456789</td></tr>
      <tr><td>(e) TELEPHONE NO.</td><td>(212) 555-0100</td></tr>
    </table>
    <table><tr><td>INSTRUCTIONS: 1(a) Name of issuer; 3(a) Title of class.</td></tr></table>
    """
    sections = partition_form144_tables(html)
    assert sections.cover_box_1_2 is not None
    assert sections.cover_box_1_2.table_index == 0
    assert sections.unparsed == []


def test_partition_merges_split_cover_tables():
    html = """
    <table><tr><td>1 (a) NAME OF ISSUER</td><td>Acme Corp</td></tr></table>
    <table>
      <tr><td>1 (d) ADDRESS OF ISSUER</td><td>STREET</td><td>CITY</td>
          <td>STATE</td><td>ZIP CODE</td><td>(e) TELEPHONE NO.</td></tr>
      <tr><td></td><td>100 Main St</td><td>New York</td><td>NY</td>
          <td>10001</td><td>(212) 555-0100</td></tr>
    </table>
    <table>
      <tr><td>2 (a) NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES ARE TO BE SOLD</td>
          <td>Jane Doe</td></tr>
      <tr><td>2 (b) RELATIONSHIP TO ISSUER</td><td>Officer</td></tr>
      <tr><td>2 (c) ADDRESS STREET CITY STATE ZIP CODE</td>
          <td>5 Oak Ave, Albany, NY 12207</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    assert sections.cover_box_1_2 is not None
    assert sections.cover_box_1_2.table_index == 0
    assert len(sections.cover_box_1_2.resolved_grid.rows) == 6


def test_table_i_classification_includes_th_headers():
    html = """
    <table>
      <tr><th>Title of the Class</th><th>Date you Acquired</th>
          <th>Nature of Acquisition Transaction</th></tr>
      <tr><td>Common Stock</td><td>01/02/2020</td><td>Open market purchase</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    assert sections.table_i is not None
    assert sections.unparsed == []


def test_table_ii_continuation_rows_merge_with_header_table():
    html = """
    <table>
      <tr><td>TABLE II — SECURITIES SOLD DURING THE PAST 3 MONTHS</td></tr>
      <tr><td>Name and Address of Seller</td><td>Title of Securities Sold</td>
          <td>Date of Sale</td><td>Amount of Securities Sold</td><td>Gross Proceeds</td></tr>
      <tr><td>Seller One</td><td>Common Stock</td><td>10/01/2024</td><td>100</td><td>$1,000</td></tr>
    </table>
    <table>
      <tr><td>Seller Two</td><td>Common Stock</td><td>10/02/2024</td><td>200</td><td>$2,000</td></tr>
      <tr><td>Seller Three</td><td>Common Stock</td><td>10/03/2024</td><td>300</td><td>$3,000</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    assert sections.table_ii is not None
    assert sections.table_ii.resolved_grid.rows[-2][0] == "Seller Two"
    assert sections.table_ii.resolved_grid.rows[-1][0] == "Seller Three"
    assert sections.unparsed == []


def test_numbered_note_and_no_report_signal_are_classified():
    html = """
    <table><tr><td>Title of the Class</td><td>Date you Acquired</td>
        <td>Nature of Acquisition Transaction</td></tr></table>
    <table><tr><td>(1) The reported amount excludes a stock split.</td></tr></table>
    <table><tr><td>TABLE II — SECURITIES SOLD DURING THE PAST 3 MONTHS</td></tr>
        <tr><td>Name and Address of Seller</td><td>Title of Securities Sold</td>
        <td>Date of Sale</td><td>Amount of Securities Sold</td><td>Gross Proceeds</td></tr></table>
    <table><tr><td>N/A</td></tr></table>
    """
    sections = partition_form144_tables(html)
    assert len(sections.remarks) == 1
    assert sections.table_ii is not None
    assert parse_table_ii_rows(sections.table_ii) == (True, [])
    assert sections.unparsed == []


def test_unparenthesized_long_table_footnote_is_preserved_as_remarks():
    note = (
        "The proceeds from the anticipated sale of the 22,650 ordinary shares "
        "that are the subject of this filing are for personal taxes payable by "
        "the reporting person from equity awards."
    )
    html = f"""
    <table><tr><td>3(a) Title of the Class</td><td>Common Stock</td></tr></table>
    <table><tr><td>1 {note}</td></tr></table>
    """
    sections = partition_form144_tables(html)
    assert len(sections.remarks) == 1
    assert sections.remarks[0].raw_node.text().endswith(note)
    assert sections.unparsed == []


def test_populated_box_three_and_signature_survive_instructions():
    html = """
    <table><tr><td>3 (a) Title of the Class Common Stock</td>
        <td>Number of Shares To Be Sold 3,100</td>
        <td>Aggregate Market Value $75,175</td>
        <td>See instructions for details.</td></tr></table>
    <table><tr><td>May 12, 2015 /s/ Michael L Snider DATE OF NOTICE
        The notice shall be signed by the person for whose account the securities are to be sold.</td></tr></table>
    """
    sections = partition_form144_tables(html)
    assert sections.proposed_sale_box_3 is not None
    assert sections.signatures
    assert sections.unparsed == []


def test_official_attention_and_file_number_text_is_boilerplate():
    html = """
    <table><tr><td>ATTENTION: This Form must be filed in electronic format by
        means of the Commission's Electronic Data Gathering, Analysis and Retrieval
        system. Filer should contact the issuer to obtain the S.E.C. file number.
    </td></tr></table>
    <table><tr><td>1 (a) NAME OF ISSUER</td><td>Acme Corp</td></tr></table>
    """
    sections = partition_form144_tables(html)
    assert sections.cover_box_1_2 is not None
    assert sections.unparsed == []


def test_instruction_container_separates_blank_form_definitions_from_data():
    html = """
    <div><p>INSTRUCTIONS:</p>
      <table><tr><td>Issuer's I.R.S. Identification Number</td></tr></table>
      <table><tr><td>Issuer's S.E.C. file number, if any</td></tr></table>
    </div>
    <div>
      <table><tr><td>(d) Aggregate market value of the securities to be sold
        as of a specified date within 10 days prior to filing of this notice</td></tr></table>
      <table><tr><td>(g) Name of each securities exchange, if any, on which
        the securities are intended to be sold</td></tr></table>
    </div>
    <div><table><tr>
      <td>3(a) Title of the Class of Securities To Be Sold</td>
      <td>(b) Broker</td><td>(c) Number of Shares</td>
      <td>(d) Aggregate Market Value</td><td>(e) Outstanding</td>
      <td>(f) Approximate Date</td><td>(g) Exchange</td>
    </tr><tr><td>Common Stock</td><td>Example Broker</td><td>100</td>
      <td>500</td><td>10,000</td><td>10/26/09</td><td>NYSE</td></tr></table></div>
    """
    sections = partition_form144_tables(html)
    assert sections.proposed_sale_box_3 is not None
    assert len(sections.proposed_sale_box_3.resolved_grid.rows) == 2
    assert sections.unparsed == []


def test_single_table_ii_continuation_row_is_retained():
    html = """
    <table>
      <tr><td>TABLE II - SECURITIES SOLD DURING THE PAST 3 MONTHS</td></tr>
      <tr><td>Name and Address of Seller</td><td>Title of Securities Sold</td>
          <td>Date of Sale</td><td>Amount of Securities Sold</td><td>Gross Proceeds</td></tr>
    </table>
    <table><tr><td>Jane Doe</td><td>Common Stock</td><td>02/03/2009</td>
        <td>2,000</td><td>$63,020</td></tr></table>
    <table><tr><td>September 11, 2020 ______________ DATE OF NOTICE</td>
        <td>(SIGNATURE)</td></tr></table>
    """
    sections = partition_form144_tables(html)
    assert sections.table_ii is not None
    assert sections.table_ii.resolved_grid.rows[-1][0] == "Jane Doe"
    assert len(sections.signatures) == 1
    assert sections.unparsed == []


def test_box3_e_to_g_continuation_is_merged_with_main_grid():
    html = """
    <table>
      <tr><td>3 (a)</td><td>(b)</td><td>(c)</td><td>(d)</td></tr>
      <tr><td>Title of the Class of Securities To Be Sold</td>
          <td>Name and Address of Each Broker</td><td>Number of Shares To Be Sold</td>
          <td>Aggregate Market Value</td></tr>
      <tr><td>Common Stock</td><td>Example Broker</td><td>1,000</td><td>$2,500</td></tr>
    </table>
    <table>
      <tr><td>(e)</td><td></td><td>(f)</td><td></td><td>(g)</td></tr>
      <tr><td>Number of Shares</td><td></td><td>Approximate</td><td></td>
          <td>Name of Each</td></tr>
      <tr><td>Outstanding</td><td></td><td>Date of Sale</td><td></td>
          <td>Securities Exchange</td></tr>
      <tr><td>10,000</td><td></td><td>08/03/2004</td><td></td><td>Nasdaq</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    assert sections.proposed_sale_box_3 is not None
    assert len(sections.proposed_sale_box_3.resolved_grid.rows) > 3
    assert sections.unparsed == []


def test_populated_box3_value_row_is_merged_with_header_grid():
    html = """
    <table><tr>
      <td>3 (a) Title of the Class of Securities To Be Sold</td>
      <td>(b) Name and Address of Each Broker</td><td>SEC USE ONLY</td>
      <td>(c) Number of Shares or Other Units To Be Sold</td>
      <td>(d) Aggregate Market Value</td>
      <td>(e) Number of Shares or Other Units Outstanding</td>
      <td>(f) Approximate Date of Sale</td><td>(g) Name of Each Securities Exchange</td>
    </tr></table>
    <table><tr><td>Ordinary Shares</td><td>Morgan Stanley Smith Barney, LLC</td>
      <td></td><td>56,000</td><td>$1,949,360</td><td>319,200,181</td>
      <td>10/26/09</td><td>NYSE</td></tr></table>
    """
    sections = partition_form144_tables(html)
    assert sections.proposed_sale_box_3 is not None
    assert len(sections.proposed_sale_box_3.resolved_grid.rows) == 2
    assert sections.unparsed == []
