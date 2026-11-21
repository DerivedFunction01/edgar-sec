from __future__ import annotations

from edgar_sec.domain.forms.families.form_c.models import FormCKind
from edgar_sec.engine.forms.form_c.xml_parser import parse_form_c_xml

_OFFERING_XML = b"""<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/formc"
                 xmlns:com="http://www.sec.gov/edgar/common">
  <headerData>
    <submissionType>C</submissionType>
    <filerInfo>
      <filer><filerCredentials>
        <filerCik>0001161291</filerCik><filerCcc>XXXXXXXX</filerCcc>
      </filerCredentials></filer>
      <liveTestFlag>LIVE</liveTestFlag>
    </filerInfo>
  </headerData>
  <formData>
    <issuerInformation>
      <issuerInfo>
        <nameOfIssuer>Phase V StevenS</nameOfIssuer>
        <legalStatus>
          <legalStatusForm>Limited Partnership</legalStatusForm>
          <jurisdictionOrganization>DC</jurisdictionOrganization>
        </legalStatus>
        <issuerWebsite>WWW.SEC.COM</issuerWebsite>
      </issuerInfo>
      <commissionCik>0000350001</commissionCik>
      <commissionFileNumber>008-100204</commissionFileNumber>
    </issuerInformation>
    <offeringInformation>
      <offeringAmount>100000</offeringAmount>
      <maximumOfferingAmount>1070000</maximumOfferingAmount>
    </offeringInformation>
  </formData>
</edgarSubmission>
"""

_WITHDRAWAL_XML = b"""<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/formc">
  <headerData>
    <submissionType>C-W</submissionType>
    <filerInfo>
      <filer><filerCredentials>
        <filerCik>0001161291</filerCik><filerCcc>XXXXXXXX</filerCcc>
      </filerCredentials></filer>
      <liveTestFlag>LIVE</liveTestFlag>
    </filerInfo>
  </headerData>
  <formData>
    <issuerInformation>
      <issuerInfo><nameOfIssuer>Phase V StevenS</nameOfIssuer></issuerInfo>
      <fileNumber>020-12345</fileNumber>
    </issuerInformation>
  </formData>
</edgarSubmission>
"""


def test_parse_offering_document() -> None:
    doc = parse_form_c_xml(_OFFERING_XML)
    assert doc is not None
    assert doc.kind is FormCKind.OFFERING
    assert doc.filer_ciks == ("0001161291",)
    assert doc.issuer.name == "Phase V StevenS"
    assert doc.issuer.commission_file_number == "008-100204"
    assert doc.issuer.legal_status_form == "Limited Partnership"
    assert doc.has_offering_information is True
    assert doc.offering_amount == "100000"
    assert doc.maximum_offering_amount == "1070000"


def test_parse_withdrawal_document() -> None:
    doc = parse_form_c_xml(_WITHDRAWAL_XML)
    assert doc is not None
    assert doc.kind is FormCKind.WITHDRAWAL
    assert doc.has_offering_information is False


def test_parse_rejects_other_documents() -> None:
    assert parse_form_c_xml(b"<notificationOfRemoval/>") is None
    assert parse_form_c_xml(b"junk") is None
