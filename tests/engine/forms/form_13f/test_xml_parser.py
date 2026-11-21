"""Tests for the Form 13F XML parser."""

from edgar_sec.engine.forms.form_13f.xml_parser import parse_form_13f_xml

_SUBMISSION = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"
 xmlns:com="http://www.sec.gov/edgar/common">
  <headerData>
    <submissionType>13F-HR</submissionType>
    <filerInfo>
      <liveTestFlag>LIVE</liveTestFlag>
      <periodOfReport>12-31-2025</periodOfReport>
    </filerInfo>
  </headerData>
  <formData>
    <coverPage>
      <reportCalendarOrQuarter>12-31-2025</reportCalendarOrQuarter>
      <isAmendment>false</isAmendment>
      <filingManager>
        <name>ACME ADVISORS LLC</name>
        <address>
          <com:street1>1 MAIN ST</com:street1>
          <com:city>BOSTON</com:city>
          <com:stateOrCountry>MA</com:stateOrCountry>
          <com:zipCode>02110</com:zipCode>
        </address>
      </filingManager>
      <reportType>13F HOLDINGS REPORT</reportType>
      <form13FFileNumber>028-12345</form13FFileNumber>
      <crdNumber>123456</crdNumber>
      <secFileNumber>801-12345</secFileNumber>
    </coverPage>
    <summaryPage>
      <otherIncludedManagersCount>2</otherIncludedManagersCount>
      <tableEntryTotal>3</tableEntryTotal>
      <tableValueTotal>9000</tableValueTotal>
      <isConfidentialOmitted>false</isConfidentialOmitted>
    </summaryPage>
  </formData>
</edgarSubmission>
"""

_INFORMATION_TABLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>AT&amp;T INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>00206R102</cusip>
    <figi>00206R107854</figi>
    <value>452</value>
    <shrsOrPrnAmt>
      <sshPrnamt>79296</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <putCall>Put</putCall>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <otherManager>1</otherManager>
    <votingAuthority>
      <Sole>0</Sole>
      <Shared>0</Shared>
      <None>79296</None>
    </votingAuthority>
  </infoTable>
</informationTable>
"""


def test_parse_submission_cover_and_summary() -> None:
    """Submission documents parse cover metadata and summary totals."""
    doc = parse_form_13f_xml(_SUBMISSION)
    assert doc.submission_type == "13F-HR"
    assert doc.manager_name == "ACME ADVISORS LLC"
    assert doc.manager_address is not None
    assert doc.manager_address.city == "BOSTON"
    assert doc.report_type == "13F HOLDINGS REPORT"
    assert doc.form13f_file_number == "028-12345"
    assert doc.crd_number == "123456"
    assert doc.sec_file_number == "801-12345"
    assert doc.other_included_managers_count == 2
    assert doc.table_entry_total == 3
    assert doc.table_value_total == 9000
    assert doc.holdings == ()


def test_parse_submission_thousands_era_scales_total() -> None:
    """Pre-2023 periods state values in thousands; model carries dollars."""
    old = _SUBMISSION.replace(b"12-31-2025", b"06-30-2020")
    doc = parse_form_13f_xml(old)
    assert doc.table_value_total == 9000 * 1000
    unscaled = parse_form_13f_xml(old, normalize_values=False)
    assert unscaled.table_value_total == 9000


def test_parse_information_table_rows() -> None:
    """Information-table documents parse typed holdings rows."""
    doc = parse_form_13f_xml(_INFORMATION_TABLE)
    assert len(doc.holdings) == 1
    row = doc.holdings[0]
    assert row.name_of_issuer == "AT&T INC"
    assert row.cusip == "00206R102"
    assert row.figi == "00206R107854"
    assert row.value == 452
    assert row.shares_or_principal == 79296
    assert row.amount_type == "SH"
    assert row.put_call == "Put"
    assert row.investment_discretion == "SOLE"
    assert row.other_managers == "1"
    assert row.voting_none == 79296
