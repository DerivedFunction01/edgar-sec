from __future__ import annotations

from edgar_sec.domain.forms.families.form_rega.models import RegAKind
from edgar_sec.engine.forms.form_rega.xml_parser import parse_rega_xml

_OFFERING_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/rega/oneafiler"
                 xmlns:com="http://www.sec.gov/edgar/common">
  <headerData>
    <submissionType>1-A</submissionType>
    <filerInfo>
      <liveTestFlag>LIVE</liveTestFlag>
      <filer>
        <issuerCredentials>
          <cik>0001663038</cik><ccc>XXXXXXXX</ccc>
        </issuerCredentials>
      </filer>
      <offeringFileNumber>024-12345</offeringFileNumber>
    </filerInfo>
  </headerData>
  <formData>
    <employeesInfo>
      <issuerName>Acme Reg A Corp.</issuerName>
      <jurisdictionOrganization>DE</jurisdictionOrganization>
      <cik>0001663038</cik>
    </employeesInfo>
    <summaryInfo>
      <indicateTier1Tier2Offering>Tier 2</indicateTier1Tier2Offering>
      <totalAggregateOffering>20000000</totalAggregateOffering>
    </summaryInfo>
  </formData>
</edgarSubmission>
"""

_ANNUAL_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/rega/onekfiler"
                 xmlns:com="http://www.sec.gov/edgar/common">
  <headerData>
    <submissionType>1-K</submissionType>
    <filerInfo>
      <liveTestFlag>LIVE</liveTestFlag>
      <filer>
        <issuerCredentials>
          <cik>0002076148</cik><ccc>XXXXXXXX</ccc>
        </issuerCredentials>
      </filer>
    </filerInfo>
  </headerData>
  <formData>
    <item1Info>
      <issuerName>Beta Holdings Inc.</issuerName>
      <cik>0002076148</cik>
      <jurisdictionOrganization>NV</jurisdictionOrganization>
    </item1Info>
    <summaryInfo>
      <commissionFileNumber>024-11223</commissionFileNumber>
    </summaryInfo>
  </formData>
</edgarSubmission>
"""

_EXIT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/rega/onezfiler"
                 xmlns:com="http://www.sec.gov/edgar/common">
  <headerData>
    <submissionType>1-Z</submissionType>
    <filerInfo>
      <liveTestFlag>LIVE</liveTestFlag>
      <filer>
        <issuerCredentials>
          <cik>0000924095</cik><ccc>XXXXXXXX</ccc>
        </issuerCredentials>
      </filer>
    </filerInfo>
  </headerData>
  <formData>
    <item1>
      <issuerName>Gamma Ventures LLC</issuerName>
      <commissionFileNumber>024-10987</commissionFileNumber>
    </item1>
    <summaryInfoOffering>
      <offeringQualificationDate>01/15/2025</offeringQualificationDate>
    </summaryInfoOffering>
    <certificationSuspension>
      <securitiesClassTitle>Common Stock</securitiesClassTitle>
    </certificationSuspension>
  </formData>
</edgarSubmission>
"""


def test_parse_offering_document() -> None:
    doc = parse_rega_xml(_OFFERING_XML)
    assert doc is not None
    assert doc.kind is RegAKind.OFFERING
    assert doc.submission_type == "1-A"
    assert doc.live_test_flag == "LIVE"
    assert doc.filer_ciks == ("0001663038",)
    assert doc.issuer_name == "Acme Reg A Corp."
    assert doc.issuer_cik == "0001663038"
    assert doc.commission_file_number == "024-12345"
    assert doc.jurisdiction == "DE"
    assert doc.tier == "Tier 2"
    assert doc.total_aggregate_offering == "20000000"
    assert doc.has_summary_block


def test_parse_annual_document() -> None:
    doc = parse_rega_xml(_ANNUAL_XML)
    assert doc is not None
    assert doc.kind is RegAKind.ANNUAL_REPORT
    assert doc.issuer_name == "Beta Holdings Inc."
    assert doc.commission_file_number == "024-11223"
    assert doc.has_summary_block
    assert not doc.has_certification


def test_parse_exit_document() -> None:
    doc = parse_rega_xml(_EXIT_XML)
    assert doc is not None
    assert doc.kind is RegAKind.EXIT_REPORT
    assert doc.issuer_name == "Gamma Ventures LLC"
    assert doc.commission_file_number == "024-10987"
    assert doc.has_summary_block
    assert doc.has_certification


def test_parse_rejects_non_rega_payloads() -> None:
    assert parse_rega_xml(b"<notificationOfRemoval/>") is None
    assert parse_rega_xml(b"not xml at all") is None
