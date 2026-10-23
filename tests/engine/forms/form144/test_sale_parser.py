"""Tests for Form 144 proposed-sale extraction."""

from edgar_sec.engine.forms.form144.sale_parser import (
    parse_proposed_sale_box_3,
)
from edgar_sec.engine.forms.form144.sections import partition_form144_tables


def test_parse_box_three_values_and_human_readable_sale_date():
    html = """
    <table>
      <tr><td>3 (a) Title of the Class</td>
          <td>(b) Name and Address of Each Broker</td>
          <td>(c) Number of Shares To Be Sold</td>
          <td>(d) Aggregate Market Value</td><td>(e) Outstanding</td>
          <td>(f) Approx Date</td><td>(g) Exchange</td></tr>
      <tr><td>Common Stock</td>
          <td>Merrill Lynch 100 Wall St, New York, NY 10005</td>
          <td>Up to 5,000</td><td>$150,000.00</td><td>10,000,000</td>
          <td>05/15/2022</td><td>NYSE</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    proposed = parse_proposed_sale_box_3(sections.proposed_sale_box_3)
    assert proposed.class_title == "Common Stock"
    assert proposed.units_to_be_sold == 5000
    assert proposed.aggregate_market_value == "150000.00"
    assert proposed.exchange_name == "NYSE"


def test_parse_box_three_values_with_glued_asof_dates():
    html = """
    <table>
      <tr><td>3 (a) Title of the Class</td>
          <td>(b) Name and Address of Each Broker</td>
          <td>(c) Number of Shares To Be Sold</td>
          <td>(d) Aggregate Market Value</td><td>(e) Outstanding</td>
          <td>(f) Approx Date</td><td>(g) Exchange</td></tr>
      <tr><td>Common Stock</td>
          <td>E-Trade 1675 Broadway, Denver, CO 80202</td>
          <td>Up to 6,025</td><td>$276,487.25<br/>05/09/2013</td>
          <td>148,762,548<br/>04/30/2013</td>
          <td>05/10/2013</td><td>NYSE</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    proposed = parse_proposed_sale_box_3(sections.proposed_sale_box_3)
    assert proposed.aggregate_market_value == "276487.25"
    assert proposed.units_outstanding == 148762548
    assert proposed.approx_sale_date == "2013-05-10"


def test_parse_box_three_values_with_explanation_suffixes():
    def render(amv_cell: str) -> str:
        return f"""
        <table>
          <tr><td>3 (a) Title of the Class</td>
              <td>(b) Name and Address of Each Broker</td>
              <td>(c) Number of Shares To Be Sold</td>
              <td>(d) Aggregate Market Value</td><td>(e) Outstanding</td>
              <td>(f) Approx Date</td><td>(g) Exchange</td></tr>
          <tr><td>Common Stock</td>
              <td>E-Trade 1675 Broadway, Denver, CO 80202</td>
              <td>6,025</td><td>{amv_cell}</td><td>148,762,548</td>
              <td>05/10/2013</td><td>NYSE</td></tr>
        </table>
        """

    for cell, expected in (
        ("$680,000 (as of 11/6/14)", "680000"),
        ("$896,670 (based on closing price on 12/02/2007)", "896670"),
        ("$47,650 as of 06/19/2019 based on the closing price", "47650"),
        ("$2,873,600 (2)", "2873600"),
        ("*$875,408.10", "875408.10"),
        ("$7,800,103.20 $466,732.80", "7800103.20"),
    ):
        sections = partition_form144_tables(render(cell))
        proposed = parse_proposed_sale_box_3(sections.proposed_sale_box_3)
        assert proposed.aggregate_market_value == expected, cell


def test_parse_box_three_columns_with_numbered_marker_cells():
    html = """
    <table>
      <tr><td>3 (a)</td><td>Title of the Class of Securities To Be Sold</td>
          <td>(b)</td><td>Name and Address of Each Broker</td><td>SEC USE ONLY</td>
          <td>(c)</td><td>Number of Shares or Other Units To Be Sold</td>
          <td>(d)</td><td>Aggregate Market Value</td><td>(e)</td>
          <td>Number of Shares or Other Units Outstanding</td><td>(f)</td>
          <td>Approximate Date of Sale</td><td>(g)</td>
          <td>Name of Each Securities Exchange</td></tr>
      <tr><td>Old Second Bancorp Inc.</td><td></td><td>Weeden &amp; Co</td><td></td><td></td>
          <td>30,000 shares</td><td></td>
          <td>Sales will be based on market value on date of sale</td><td></td>
          <td>13,761,218</td><td></td><td>01-30-09</td><td></td><td>Nasdaq</td><td></td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    proposed = parse_proposed_sale_box_3(sections.proposed_sale_box_3)
    assert proposed.class_title == "Old Second Bancorp Inc."
    assert proposed.broker is not None and proposed.broker.name == "Weeden & Co"
    assert proposed.units_to_be_sold == 30000
    assert proposed.units_outstanding == 13761218
    assert proposed.approx_sale_date == "01-30-09"
    assert proposed.exchange_name == "NASDAQ"
    assert proposed.aggregate_market_value is None


def test_parse_box_three_source_backed_sibling_continuation():
    html = """
    <table>
      <tr><td>3 (a)</td><td>(b)</td><td>(c)</td><td>(d)</td></tr>
      <tr><td>Title of the Class of Securities To Be Sold</td>
          <td>Name and Address of Each Broker</td>
          <td>Number of Shares To Be Sold</td><td>Aggregate Market Value</td></tr>
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
    proposed = parse_proposed_sale_box_3(sections.proposed_sale_box_3)
    assert proposed.class_title == "Common Stock"
    assert proposed.broker is not None and proposed.broker.name == "Example Broker"
    assert proposed.units_to_be_sold == 1000
    assert proposed.aggregate_market_value == "2500"
    assert proposed.units_outstanding == 10000
    assert proposed.approx_sale_date == "2004-08-03"
    assert proposed.exchange_name == "NASDAQ"


def test_parse_data_row_continued_after_box3_header():
    html = """
    <table><tr>
      <td>3 (a) Title of the Class of Securities To Be Sold</td>
      <td>(b) Name and Address of Each Broker</td><td>SEC USE ONLY</td>
      <td>(c) Number of Shares or Other Units To Be Sold</td>
      <td>(d) Aggregate Market Value</td>
      <td>(e) Number of Shares or Other Units Outstanding</td>
      <td>(f) Approximate Date of Sale</td><td>(g) Name of Each Securities Exchange</td>
    </tr></table>
    <table><tr><td>Ordinary Shares</td><td><div>Morgan Stanley Smith Barney, LLC</div>
      <div>285 Clyde Morris Bl. Ste. 100</div>
      <div>Ormond Beach, FL 32174</div></td>
      <td></td><td>56,000</td><td>$1,949,360</td><td>319,200,181</td>
      <td>10/26/09</td><td>NYSE</td></tr></table>
    """
    sections = partition_form144_tables(html)
    proposed = parse_proposed_sale_box_3(sections.proposed_sale_box_3)
    assert proposed.class_title == "Ordinary Shares"
    assert proposed.broker is not None
    assert proposed.broker.name == "Morgan Stanley Smith Barney, LLC"
    assert proposed.broker.street1 == "285 Clyde Morris Bl. Ste. 100"
    assert proposed.broker.city == "Ormond Beach"
    assert proposed.broker.state_or_country == "FL"
    assert proposed.broker.zip_code == "32174"
    assert proposed.units_to_be_sold == 56000
    assert proposed.aggregate_market_value == "1949360"
    assert proposed.units_outstanding == 319200181
    assert proposed.approx_sale_date == "10/26/09"
    assert proposed.exchange_name == "NYSE"


def test_parse_box3_values_in_spacer_columns_after_marked_labels():
    html = """
    <table><tr>
      <td>(a) Title of the Class of Securities to be Sold</td>
      <td>(b) Name and Address of Each Broker</td><td>SEC USE ONLY</td>
      <td>(c) Number of Shares or Other Units to be Sold</td><td></td>
      <td>(d) Aggregate Market Value</td><td></td>
      <td>(e) Number of Shares or Other Units Outstanding</td><td></td>
      <td>(f) Approximate Date of Sale</td><td>(g) Name of Each Securities Exchange</td>
    </tr><tr>
      <td>Common Shares w/o Par Value</td><td>McDonald Investments</td><td></td>
      <td></td><td>12,200</td><td></td><td>$463,600.00</td>
      <td></td><td>34,602,416</td><td>2/27/04</td><td>NASDQ</td>
    </tr><tr><td></td><td>4910 Tiedeman Road</td><td></td><td></td><td></td>
      <td></td><td></td><td></td><td></td><td></td><td></td>
    </tr><tr><td></td><td>Brooklyn, OH 44144</td><td></td><td></td><td></td>
      <td></td><td></td><td></td><td></td><td></td><td></td>
    </tr></table>
    """
    sections = partition_form144_tables(html)
    proposed = parse_proposed_sale_box_3(sections.proposed_sale_box_3)
    assert proposed.class_title == "Common Shares w/o Par Value"
    assert proposed.broker is not None
    assert proposed.broker.name == "McDonald Investments"
    assert proposed.broker.street1 == "4910 Tiedeman Road"
    assert proposed.broker.city == "Brooklyn"
    assert proposed.broker.state_or_country == "OH"
    assert proposed.broker.zip_code == "44144"
    assert proposed.units_to_be_sold == 12200
    assert proposed.aggregate_market_value == "463600.00"
    assert proposed.units_outstanding == 34602416
    assert proposed.approx_sale_date == "2/27/04"
    assert proposed.exchange_name == "NASDAQ"


def test_nearby_header_rows_and_trailing_instructions_bound_box3_data():
    html = """
    <table>
      <tr><td>FORM 144 Notice; transmit the notice to a broker.</td></tr>
      <tr><td>1(a) Name of issuer</td><td>ACME Corp.</td></tr>
      <tr><td>1(b) IRS identification number</td><td>12-3456789</td></tr>
      <tr><td>1(d) Issuer address, including zip code</td>
          <td>22 High Street, Seattle, WA 98101</td></tr>
      <tr><td>2(a) Name of person for whose account securities are to be sold</td>
          <td>Jane Doe</td></tr>
      <tr><td>2(b) Relationship to issuer</td><td>Officer</td></tr>
      <tr><td>2(c) Such person's address, including zip code</td>
          <td>22 High Street, Seattle, WA 98101</td></tr>
      <tr><td>Cover-page boilerplate ends.</td></tr>
      <tr><td>Additional filing instructions.</td></tr>
      <tr><td>3(a) Title of the Class of Securities To Be Sold</td>
          <td>3(b) Name and Address of Each Broker</td>
          <td>3(c) Number of Shares To Be Sold</td>
          <td>3(d) Aggregate Market Value</td>
          <td>3(e) Number of Shares Outstanding</td>
          <td>3(f) Approximate Date of Sale</td>
          <td>3(g) Name of Each Securities Exchange</td></tr>
      <tr><td>Common Stock</td><td>Example Broker</td><td>100</td><td>500</td>
          <td>10,000</td><td>10/26/09</td><td>NYSE</td></tr>
      <tr><td>INSTRUCTIONS: 3(c) Number of shares to be sold means total units.</td></tr>
    </table>
    """
    sections = partition_form144_tables(html)
    proposed = parse_proposed_sale_box_3(sections.proposed_sale_box_3)
    assert proposed.class_title == "Common Stock"
    assert proposed.broker is not None and proposed.broker.name == "Example Broker"
    assert proposed.units_to_be_sold == 100
    assert proposed.aggregate_market_value == "500"
    assert proposed.units_outstanding == 10000
    assert proposed.approx_sale_date == "10/26/09"
    assert proposed.exchange_name == "NYSE"
