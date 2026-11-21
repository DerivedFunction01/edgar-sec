"""Tests for the Form N-MFP XML parser."""

from edgar_sec.engine.forms.form_nmfp.xml_parser import parse_nmfp_xml

_GEN3 = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nmfp3">
  <headerData><submissionType>N-MFP3</submissionType></headerData>
  <formData>
    <generalInfo>
      <reportDate>2025-06-30</reportDate>
      <registrantFullName>ACME TRUST</registrantFullName>
      <cik>0000123456</cik>
      <nameOfSeries>ACME GOVERNMENT FUND</nameOfSeries>
      <leiOfSeries>2549004B125C89JKPS95</leiOfSeries>
      <seriesId>S000000001</seriesId>
    </generalInfo>
    <classLevelInfo><classId>C000000001</classId></classLevelInfo>
    <scheduleOfPortfolioSecuritiesInfo>
      <nameOfIssuer>United States Treasury</nameOfIssuer>
      <titleOfIssuer>T-BILL</titleOfIssuer>
      <CUSIPMember>912797PU5</CUSIPMember>
      <investmentCategory>U.S. Treasury Debt</investmentCategory>
      <investmentMaturityDateWAM>2025-07-01</investmentMaturityDateWAM>
      <investmentMaturityDateWAL>2025-07-01</investmentMaturityDateWAL>
      <includingValueOfAnySponsorSupport>9000.00</includingValueOfAnySponsorSupport>
      <percentageOfMoneyMarketFundNetAssets>0.88</percentageOfMoneyMarketFundNetAssets>
      <dailyLiquidAssetSecurityFlag>Y</dailyLiquidAssetSecurityFlag>
      <weeklyLiquidAssetSecurityFlag>Y</weeklyLiquidAssetSecurityFlag>
      <illiquidSecurityFlag>N</illiquidSecurityFlag>
    </scheduleOfPortfolioSecuritiesInfo>
  </formData>
</edgarSubmission>
"""

_GEN1 = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nmfp">
  <submissionType>N-MFP</submissionType>
  <DocumentPeriodEndDate>2013-03-31</DocumentPeriodEndDate>
  <EntityCentralIndexKey>0000877243</EntityCentralIndexKey>
  <seriesId>s000004036</seriesId>
</edgarSubmission>
"""


def test_parse_nmfp_gen3() -> None:
    """Generation 3 identity and schedule rows parse into the model."""
    doc = parse_nmfp_xml(_GEN3)
    assert doc.generation == 3
    assert doc.submission_type == "N-MFP3"
    assert doc.series_name == "ACME GOVERNMENT FUND"
    assert doc.report_date == "2025-06-30"
    assert doc.class_count == 1
    assert len(doc.securities) == 1
    row = doc.securities[0]
    assert row.cusip == "912797PU5"
    assert row.percent_of_net_assets == "0.88"


def test_parse_nmfp_gen1_header_only() -> None:
    """Generation 1 yields its flat header identity, no schedule rows."""
    doc = parse_nmfp_xml(_GEN1)
    assert doc.generation == 1
    assert doc.submission_type == "N-MFP"
    assert doc.report_date == "2013-03-31"
    assert doc.registrant_cik == "0000877243"
    assert doc.securities == ()
