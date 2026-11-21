from __future__ import annotations

from edgar_sec.engine.forms.form_25nse.xml_parser import parse_form_25nse_xml

_BARE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<notificationOfRemoval>
  <schemaVersion>X0203</schemaVersion>
  <exchange>
    <cik>0001099219</cik>
    <ccc>xxxxxxxx</ccc>
    <entityName>NYSE American LLC</entityName>
  </exchange>
  <issuer>
    <cik>0001234567</cik>
    <entityName>Acme Corp</entityName>
    <fileNumber>001-00001</fileNumber>
    <address>
      <street1>123 Main St</street1>
      <city>Anywhere</city>
      <stateOrCountryCode>VA</stateOrCountryCode>
      <zipCode>21212</zipCode>
    </address>
    <telephoneNumber>(202) 123-4567</telephoneNumber>
  </issuer>
  <descriptionClassSecurity>Class A and Class B</descriptionClassSecurity>
  <ruleProvision>17 CFR 240.12d2-2(a)(2)</ruleProvision>
  <signatureData>
    <signatureName>John Q. Public</signatureName>
    <signatureTitle>Chief Executive Officer</signatureTitle>
    <signatureDate>2005-02-01</signatureDate>
  </signatureData>
</notificationOfRemoval>
"""

_WRAPPER_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission>
  <submissionType>25-NSE</submissionType>
  <primaryDocument>
    <documentName>primary_doc.xml</documentName>
    <documentType>25-NSE</documentType>
    <documentBlock>
      <notificationOfRemoval>
        <exchange><cik>0001099219</cik><ccc>xxxxxxxx</ccc></exchange>
        <issuer>
          <cik>0001234567</cik>
          <fileNumber>001-00001</fileNumber>
          <address><street1>123 Main St</street1><city>Anywhere</city>
          <stateOrCountryCode>VA</stateOrCountryCode><zipCode>21212</zipCode></address>
        </issuer>
        <descriptionClassSecurity>Common Stock</descriptionClassSecurity>
        <ruleProvision>17 CFR 240.12d2-2(b)</ruleProvision>
        <signatureData>
          <signatureName>John Q. Public</signatureName>
          <signatureTitle>Chief Executive Officer</signatureTitle>
          <signatureDate>2005-02-01</signatureDate>
        </signatureData>
      </notificationOfRemoval>
    </documentBlock>
  </primaryDocument>
</edgarSubmission>
"""


def test_parse_bare_document() -> None:
    doc = parse_form_25nse_xml(_BARE_XML)
    assert doc is not None
    assert doc.schema_version == "X0203"
    assert doc.exchange.entity_name == "NYSE American LLC"
    assert doc.issuer.file_number == "001-00001"
    assert doc.issuer.address is not None
    assert doc.issuer.address.zip_code == "21212"
    assert doc.rule_provision == "17 CFR 240.12d2-2(a)(2)"
    assert doc.signature.date == "2005-02-01"


def test_parse_wrapped_submission() -> None:
    doc = parse_form_25nse_xml(_WRAPPER_XML)
    assert doc is not None
    assert doc.schema_version is None
    assert doc.issuer.cik == "0001234567"
    assert doc.rule_provision == "17 CFR 240.12d2-2(b)"


def test_parse_rejects_non_25nse_payloads() -> None:
    assert parse_form_25nse_xml(b"<html><body>no</body></html>") is None
    assert parse_form_25nse_xml(b"not xml at all") is None
    assert parse_form_25nse_xml(b"") is None
