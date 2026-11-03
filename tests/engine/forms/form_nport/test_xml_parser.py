"""Tests for the Form N-PORT XML parser."""

from edgar_sec.engine.forms.form_nport.xml_parser import parse_nport_xml

_SUBMISSION = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
  <headerData>
    <submissionType>NPORT-P</submissionType>
    <isConfidential>false</isConfidential>
    <filerInfo><filer><issuerCredentials><cik>0000123456</cik>
    </issuerCredentials></filer></filerInfo>
  </headerData>
  <formData>
    <genInfo>
      <regName>ACME FUND TRUST</regName>
      <regFileNumber>811-00000</regFileNumber>
      <regCik>0000123456</regCik>
      <seriesName>ACME GROWTH FUND</seriesName>
      <repPdEnd>2025-03-31</repPdEnd>
      <repPdDate>2025-01-31</repPdDate>
      <isFinalFiling>N</isFinalFiling>
    </genInfo>
    <fundInfo>
      <totAssets>1000.00</totAssets>
      <totLiabs>25.00</totLiabs>
      <netAssets>975.00</netAssets>
    </fundInfo>
    <invstOrSecs>
      <invstOrSec>
        <name>ACME CORP</name>
        <lei>529900LGRXWX2ACMWR86</lei>
        <title>ACME COMMON</title>
        <cusip>001000000</cusip>
        <identifiers><isin value="US0010000000"/></identifiers>
        <balance>100.0</balance>
        <units>NS</units>
        <currencyConditional curCd="USD" exchangeRt="1.0"/>
        <valUSD>500.00</valUSD>
        <pctVal>51.28</pctVal>
        <payoffProfile>Long</payoffProfile>
        <assetCat>EC</assetCat>
        <issuerCat>CORP</issuerCat>
        <invCountry>US</invCountry>
        <isRestrictedSec>N</isRestrictedSec>
        <fairValLevel>1</fairValLevel>
      </invstOrSec>
    </invstOrSecs>
  </formData>
</edgarSubmission>
"""


def test_parse_nport_submission() -> None:
    """Cover, fund totals, and investment rows parse into the model."""
    doc = parse_nport_xml(_SUBMISSION)
    assert doc.submission_type == "NPORT-P"
    assert doc.registrant_name == "ACME FUND TRUST"
    assert doc.series_name == "ACME GROWTH FUND"
    assert doc.report_period_end == "2025-03-31"
    assert doc.net_assets == "975.00"
    assert doc.filer_cik == "0000123456"
    assert len(doc.investments) == 1
    row = doc.investments[0]
    assert row.cusip == "001000000"
    assert row.isin == "US0010000000"
    assert row.currency_code == "USD"
    assert row.value_usd == "500.00"
    assert row.payoff_profile == "Long"
