"""Tests for Form D XML renderer."""

from edgar_sec.domain.forms.families.form_d.models import (
    FormDDocument,
    IssuerAddress,
    OfferingSalesAmounts,
    PrimaryIssuer,
    RelatedPerson,
    Signatory,
)
from edgar_sec.engine.forms.form_d.renderer import render_form_d_to_xml
from edgar_sec.engine.forms.form_d.xml_parser import parse_form_d_xml
from edgar_sec.engine.forms.form_d.renderer import build_form_d_xml

_SAMPLE_XML = b"""<?xml version="1.0"?>
<edgarSubmission>
    <schemaVersion>X0707</schemaVersion>
    <submissionType>D</submissionType>
    <testOrLive>LIVE</testOrLive>
    <primaryIssuer>
        <cik>0001487198</cik>
        <entityName>ASPEN GROUP, INC.</entityName>
        <issuerAddress>
            <street1>1660 SOUTH ALBION STREET</street1>
            <city>DENVER</city>
            <stateOrCountry>CO</stateOrCountry>
            <zipCode>80222</zipCode>
        </issuerAddress>
    </primaryIssuer>
</edgarSubmission>"""


def test_render_form_d_passthrough() -> None:
    """Verify native XML passthrough returns identical content."""
    output = render_form_d_to_xml(_SAMPLE_XML)
    assert output.content == _SAMPLE_XML
    assert len(output.sidecars) == 1
    assert output.sidecars[0].name == "unparsed_sections.json"


def test_build_form_d_xml_from_model() -> None:
    """Verify building canonical XML from FormDDocument."""
    doc = parse_form_d_xml(_SAMPLE_XML)
    output = build_form_d_xml(doc)
    assert b"ASPEN GROUP, INC." in output.content
    assert b"<submissionType>D</submissionType>" in output.content


_FULL_DOC = FormDDocument(
    schema_version="X0707",
    submission_type="D",
    test_or_live="LIVE",
    primary_issuer=PrimaryIssuer(
        cik="0001487198",
        entity_name="ASPEN GROUP, INC.",
        address=IssuerAddress(
            street1="1 MAIN ST",
            street2=None,
            city="DENVER",
            state_or_country="CO",
            state_or_country_desc=None,
            zip_code="80222",
        ),
        phone_number="303-555-0100",
        jurisdiction="DE",
        entity_type="Corporation",
        year_of_inc="2010",
    ),
    related_persons=(
        RelatedPerson(
            first_name="JANE",
            middle_name=None,
            last_name="DOE",
            address=None,
            relationships=("Executive Officer", "Director"),
            clarification=None,
        ),
    ),
    offering_amounts=OfferingSalesAmounts(
        total_offering_amount=5000000.0,
        total_amount_sold=1250000.0,
        total_remaining=3750000.0,
    ),
    signatures=(
        Signatory(
            issuer_name="ASPEN GROUP, INC.",
            signature_name="/s/ JANE DOE",
            name_of_signer="JANE DOE",
            signature_title="CEO",
            signature_date="2026-01-15",
        ),
    ),
    industry_group="Other",
    federal_exemptions=("506b",),
)

_FULL_XML = (
    b"<?xml version='1.0' encoding='utf-8'?>\n"
    b"<edgarSubmission><schemaVersion>X0707</schemaVersion>"
    b"<submissionType>D</submissionType><testOrLive>LIVE</testOrLive>"
    b"<primaryIssuer><cik>0001487198</cik>"
    b"<entityName>ASPEN GROUP, INC.</entityName>"
    b"<issuerAddress><street1>1 MAIN ST</street1><street2 />"
    b"<city>DENVER</city><stateOrCountry>CO</stateOrCountry>"
    b"<stateOrCountryDescription /><zipCode>80222</zipCode></issuerAddress>"
    b"<issuerPhoneNumber>303-555-0100</issuerPhoneNumber>"
    b"<jurisdictionOfInc>DE</jurisdictionOfInc>"
    b"<entityType>Corporation</entityType></primaryIssuer>"
    b"<relatedPersonsList><relatedPersonInfo><relatedPersonName>"
    b"<firstName>JANE</firstName><middleName /><lastName>DOE</lastName>"
    b"</relatedPersonName><relatedPersonRelationshipList>"
    b"<relationship>Executive Officer</relationship>"
    b"<relationship>Director</relationship>"
    b"</relatedPersonRelationshipList><relationshipClarification />"
    b"</relatedPersonInfo></relatedPersonsList>"
    b"<offeringData><industryGroup>"
    b"<industryGroupType>Other</industryGroupType></industryGroup>"
    b"<federalExemptionsExclusions><item>506b</item>"
    b"</federalExemptionsExclusions><offeringSalesAmounts>"
    b"<totalOfferingAmount>5000000</totalOfferingAmount>"
    b"<totalRemaining>3750000</totalRemaining>"
    b"<totalAmountSold>1250000</totalAmountSold></offeringSalesAmounts>"
    b"<signatureBlock><signature>"
    b"<issuerName>ASPEN GROUP, INC.</issuerName>"
    b"<signatureName>/s/ JANE DOE</signatureName>"
    b"<nameOfSigner>JANE DOE</nameOfSigner>"
    b"<signatureTitle>CEO</signatureTitle>"
    b"<signatureDate>2026-01-15</signatureDate></signature>"
    b"</signatureBlock></offeringData></edgarSubmission>"
)


def test_build_form_d_xml_golden_bytes() -> None:
    """Pin the canonical bytes for a fully populated document."""
    output = build_form_d_xml(_FULL_DOC)
    assert output.content == _FULL_XML
    assert output.sidecars[0].content == b'{"unparsed_sections":[]}'


def test_build_form_d_xml_indefinite_amounts_golden() -> None:
    """Pin the canonical bytes for the indefinite-amounts branch."""
    doc = FormDDocument(
        schema_version="X0707",
        submission_type="D/A",
        test_or_live="TEST",
        primary_issuer=PrimaryIssuer(
            cik="1",
            entity_name="X",
            address=None,
            phone_number=None,
            jurisdiction=None,
            entity_type=None,
            year_of_inc=None,
        ),
        related_persons=(),
        offering_amounts=OfferingSalesAmounts(
            total_offering_amount=None,
            total_amount_sold=None,
            total_remaining=None,
            is_indefinite=True,
        ),
        signatures=(),
    )
    output = build_form_d_xml(doc)
    assert output.content == (
        b"<?xml version='1.0' encoding='utf-8'?>\n"
        b"<edgarSubmission><schemaVersion>X0707</schemaVersion>"
        b"<submissionType>D/A</submissionType><testOrLive>TEST</testOrLive>"
        b"<primaryIssuer><cik>1</cik><entityName>X</entityName>"
        b"<issuerPhoneNumber /><jurisdictionOfInc /><entityType />"
        b"</primaryIssuer><offeringData><offeringSalesAmounts>"
        b"<totalOfferingAmount>Indefinite</totalOfferingAmount>"
        b"<totalRemaining>Indefinite</totalRemaining><totalAmountSold />"
        b"</offeringSalesAmounts></offeringData></edgarSubmission>"
    )
