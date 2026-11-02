import json
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.common.signatures import SignatureBlock, Signatory
from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    AddressDetails,
    BeneficialOwnershipDocument,
    CoverItemEvidence,
    EvidenceState,
    IssuerMetadata,
    NarrativeField,
    NarrativeItem,
    ReportingPersonCover,
)
from edgar_sec.domain.forms.families.beneficial_ownership.taxonomy import (
    SCHEDULE_13D_XML_NAMESPACE,
    SCHEDULE_13G_XML_NAMESPACE,
)
from edgar_sec.engine.forms.beneficial_ownership.render_to_xml import (
    build_beneficial_ownership_xml,
    build_schedule13d_xml,
)


def test_generated_xml_uses_sec_namespaces_and_repeated_standard_fields() -> None:
    person = ReportingPersonCover(
        (
            CoverItemEvidence(
                1,
                "Name of Reporting Person Ada Entity",
                "Ada Entity",
                EvidenceState.VALUE,
            ),
            CoverItemEvidence(
                2, "Group membership", "a. [ ] b. [X]", EvidenceState.VALUE
            ),
            CoverItemEvidence(
                4,
                "Source of Funds 00 WC and PF",
                "00-Funds of investment advisory clients WC and PF",
                EvidenceState.VALUE,
            ),
            CoverItemEvidence(5, "Legal proceedings [X]", "[X]", EvidenceState.CHECKED),
            CoverItemEvidence(
                7, "Sole voting power", "10,000 shares", EvidenceState.VALUE
            ),
            CoverItemEvidence(
                13, "Percent of class", "5.25% (Item 5)", EvidenceState.VALUE
            ),
            CoverItemEvidence(
                14,
                "Type IN, OO, and 00",
                "IN, OO, 00-Private Foundation",
                EvidenceState.VALUE,
            ),
        ),
        comment_content="Source comment.",
    )
    document = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(
            issuer_name="Example & Co.",
            security_class="Common Stock",
            cusip="1234567890123",
            event_date="2026-10-18",
            issuer_address=AddressDetails("123 Main St", street1="123 Main St"),
        ),
        reporting_persons=(person, person),
        narrative_items=(
            NarrativeItem(4, "Purpose of Transaction", "Buy & hold.", 0, 15),
        ),
        signature_block=SignatureBlock((Signatory("Ada Signer", date="2026-10-18"),)),
        submission_type="SCHEDULE 13D/A",
        previous_accession_number="0000000000-26-000001",
    )

    output = build_schedule13d_xml(document)
    root = ET.fromstring(output.content)
    ns = {"s": SCHEDULE_13D_XML_NAMESPACE, "com": "http://www.sec.gov/edgar/common"}

    assert root.findtext("s:schemaVersion", namespaces=ns) == "X0202"
    assert (
        root.findtext("s:headerData/s:previousAccessionNumber", namespaces=ns)
        == "0000000000-26-000001"
    )
    assert (
        root.findtext("s:headerData/s:submissionType", namespaces=ns)
        == "SCHEDULE 13D/A"
    )
    assert root.findtext(".//s:issuerCusipNumber", namespaces=ns) == "1234567890123"
    assert root.findtext(".//s:memberOfGroup", namespaces=ns) == "b"
    assert root.findtext(".//com:street1", namespaces=ns) == "123 Main St"
    assert [node.text for node in root.findall(".//s:soleVotingPower", ns)] == [
        "10000",
        "10000",
    ]
    assert [node.text for node in root.findall(".//s:percentOfClass", ns)] == [
        "5.25",
        "5.25",
    ]
    assert [node.text for node in root.findall(".//s:fundType", ns)] == [
        "WC",
        "PF",
        "WC",
        "PF",
    ]
    assert [node.text for node in root.findall(".//s:typeOfReportingPerson", ns)] == [
        "IN",
        "OO",
        "IN",
        "OO",
    ]
    assert len(root.findall(".//s:reportingPersonInfo", ns)) == 2
    assert len(root.findall(".//s:commentContent", ns)) == 2
    assert root.findtext(".//s:legalProceedings", namespaces=ns) == "Y"
    assert (
        root.findtext(".//s:item4/s:transactionPurpose", namespaces=ns) == "Buy & hold."
    )
    assert (
        root.findtext(".//s:signatureDetails/s:signature", namespaces=ns)
        == "Ada Signer"
    )
    assert root.findtext(".//s:date", namespaces=ns) == "10-18-2026"
    assert root.find("s:extractionProvenance", ns) is None
    assert root.find("s:unparsedSections", ns) is None
    assert output.sidecars[0].name == "unparsed_sections.json"


def test_signature_date_uses_explicit_event_year_for_two_digit_year() -> None:
    document = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(event_date="2020-01-01"),
        reporting_persons=(),
        signature_block=SignatureBlock(
            (Signatory("Ada Signer", date="January 2, 20"),)
        ),
    )

    output = build_schedule13d_xml(document)
    root = ET.fromstring(output.content)

    assert (
        root.findtext(".//{http://www.sec.gov/edgar/schedule13D}date") == "01-02-2020"
    )
    date_evidence = next(
        record
        for record in json.loads(output.sidecars[0].content)["unparsed_sections"]
        if record["role"].startswith("normalization.date:")
        and record["role"].endswith("signatureDetails.date")
    )
    assert date_evidence["content"] == "January 2, 20"
    assert date_evidence["reported_year_anchor"] == 2020


def test_signature_date_falls_back_to_filing_date() -> None:
    document = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(),
        reporting_persons=(),
        signature_block=SignatureBlock((Signatory("Ada Signer"),)),
    )

    output = build_beneficial_ownership_xml(document, filing_date="2001-01-19")
    root = ET.fromstring(output.content)

    signature_date = root.findtext(
        ".//s:date", namespaces={"s": SCHEDULE_13D_XML_NAMESPACE}
    )
    assert signature_date == "01-19-2001"


def test_schedule13g_uses_its_cover_person_and_items_schema_tags() -> None:
    person = ReportingPersonCover(
        (
            CoverItemEvidence(
                1,
                "Reporting person",
                "Jane Doe",
                EvidenceState.VALUE,
                tag="reportingPersonName",
            ),
            CoverItemEvidence(
                2, "Group", "a", EvidenceState.VALUE, tag="memberOfGroup"
            ),
            CoverItemEvidence(
                4,
                "Citizenship",
                "CA",
                EvidenceState.VALUE,
                tag="citizenshipOrOrganization",
            ),
            CoverItemEvidence(
                5,
                "Sole voting",
                "1,000 shares",
                EvidenceState.VALUE,
                tag="soleVotingPower",
            ),
            CoverItemEvidence(
                6,
                "Shared voting",
                "0",
                EvidenceState.VALUE,
                tag="sharedVotingPower",
            ),
            CoverItemEvidence(
                7,
                "Sole dispositive",
                "1,000",
                EvidenceState.VALUE,
                tag="soleDispositivePower",
            ),
            CoverItemEvidence(
                8,
                "Shared dispositive",
                "0",
                EvidenceState.VALUE,
                tag="sharedDispositivePower",
            ),
            CoverItemEvidence(
                9,
                "Aggregate",
                "1,000",
                EvidenceState.VALUE,
                tag="aggregateAmountOwned",
            ),
            CoverItemEvidence(
                11,
                "Class percent",
                "5.25%",
                EvidenceState.VALUE,
                tag="percentOfClass",
            ),
            CoverItemEvidence(
                12,
                "Type",
                "IN",
                EvidenceState.VALUE,
                tag="typeOfReportingPerson",
            ),
        )
    )
    document = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(security_class="Common stock", event_date="2024-01-02"),
        reporting_persons=(person,),
        narrative_items=(NarrativeItem(3, "Item 3", "Unparsed filing text", 4, 24),),
        submission_type="SCHEDULE 13G",
        form_family="13G",
    )

    output = build_schedule13d_xml(document)
    root = ET.fromstring(output.content)
    namespace = {"s": SCHEDULE_13G_XML_NAMESPACE}

    assert (
        root.findtext(".//s:eventDateRequiresFilingThisStatement", namespaces=namespace)
        == "01-02-2024"
    )
    assert root.findtext(".//s:memberGroup", namespaces=namespace) == "a"
    assert (
        root.findtext(
            ".//s:reportingPersonBeneficiallyOwnedAggregateNumberOfShares",
            namespaces=namespace,
        )
        == "1000"
    )
    assert root.findtext(".//s:classPercent", namespaces=namespace) == "5.25"
    assert root.find(".//s:items", namespace) is not None
    not_applicable = root.findtext(
        ".//s:items/s:item3/s:notApplicableFlag", namespaces=namespace
    )
    assert not_applicable == "Y"
    assert root.find(".//s:items/s:item3/s:typeOfPersonFiling", namespace) is None
    sections = json.loads(output.sidecars[0].content)["unparsed_sections"]
    assert any(section["role"] == "item3.unparsed" for section in sections)


def test_percent_of_class_quantization_and_zero_trimming() -> None:
    person = ReportingPersonCover(
        (
            CoverItemEvidence(
                1, "Name", "Person A", EvidenceState.VALUE, tag="reportingPersonName"
            ),
            CoverItemEvidence(
                9,
                "Aggregate",
                "725,715 shares",
                EvidenceState.VALUE,
                tag="aggregateAmountOwned",
            ),
            CoverItemEvidence(
                11, "Percent", "13.000%", EvidenceState.VALUE, tag="percentOfClass"
            ),
            CoverItemEvidence(
                12, "Type", "HC", EvidenceState.VALUE, tag="typeOfReportingPerson"
            ),
        )
    )
    doc = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(security_class="Common", event_date="2024-01-02"),
        reporting_persons=(person,),
        submission_type="SCHEDULE 13G",
        form_family="13G",
    )
    output = build_schedule13d_xml(doc)
    root = ET.fromstring(output.content)
    ns = {"s": SCHEDULE_13G_XML_NAMESPACE}
    assert root.findtext(".//s:classPercent", namespaces=ns) == "13"


def test_schedule13g_item4_xml_rendering() -> None:
    person = ReportingPersonCover(
        (
            CoverItemEvidence(
                1, "Name", "Person A", EvidenceState.VALUE, tag="reportingPersonName"
            ),
        )
    )
    doc = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(event_date="2024-01-02"),
        reporting_persons=(person,),
        narrative_items=(
            NarrativeItem(
                4,
                "Item 4",
                "Item 4 raw text",
                0,
                100,
                parsed_fields=(
                    NarrativeField("aggregateAmountOwned", "500000", 10, 20, "500,000"),
                    NarrativeField("percentOfClass", "5.5", 30, 35, "5.5%"),
                    NarrativeField("soleVotingPower", "500000", 40, 50, "500,000"),
                ),
            ),
        ),
        submission_type="SCHEDULE 13G",
        form_family="13G",
    )
    output = build_schedule13d_xml(doc)
    root = ET.fromstring(output.content)
    ns = {"s": SCHEDULE_13G_XML_NAMESPACE}
    assert (
        root.findtext(".//s:item4/s:amountBeneficiallyOwned", namespaces=ns) == "500000"
    )
    assert root.findtext(".//s:item4/s:classPercent", namespaces=ns) == "5.5"
    assert (
        root.findtext(
            ".//s:item4/s:numberOfSharesPersonHas/s:solePowerOrDirectToVote",
            namespaces=ns,
        )
        == "500000"
    )


def test_schedule13g_item10_certifications_xml_rendering() -> None:
    person = ReportingPersonCover(
        (
            CoverItemEvidence(
                1, "Name", "Person A", EvidenceState.VALUE, tag="reportingPersonName"
            ),
        )
    )
    doc = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(event_date="2024-01-02"),
        reporting_persons=(person,),
        narrative_items=(
            NarrativeItem(
                10,
                "Item 10",
                "Certification text",
                0,
                50,
                parsed_fields=(
                    NarrativeField(
                        "certifications",
                        "Securities not acquired for control purposes.",
                        0,
                        50,
                        "Securities not acquired for control purposes.",
                    ),
                ),
            ),
        ),
        submission_type="SCHEDULE 13G",
        form_family="13G",
    )
    output = build_schedule13d_xml(doc)
    root = ET.fromstring(output.content)
    ns = {"s": SCHEDULE_13G_XML_NAMESPACE}
    assert (
        root.findtext(".//s:item10/s:certifications", namespaces=ns)
        == "Securities not acquired for control purposes."
    )


def test_schedule13g_items_3_to_9_xml_rendering() -> None:
    """Verify 13G Items 3, 5, 6, 7, 8, 9 render to conforming XML."""
    person = ReportingPersonCover(
        (
            CoverItemEvidence(
                1, "Name", "Fund LP", EvidenceState.VALUE, tag="reportingPersonName"
            ),
        )
    )
    doc = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(event_date="2024-01-02"),
        reporting_persons=(person,),
        narrative_items=(
            NarrativeItem(
                3,
                "Item 3",
                "N/A",
                0,
                10,
                parsed_fields=(NarrativeField("notApplicableFlag", "Y", 0, 3, "N/A"),),
            ),
            NarrativeItem(
                5,
                "Item 5",
                "Ceased",
                11,
                20,
                parsed_fields=(
                    NarrativeField("is5PercentCessation", "Y", 11, 15, "Y"),
                ),
            ),
            NarrativeItem(
                6,
                "Item 6",
                "Clients",
                21,
                30,
                parsed_fields=(
                    NarrativeField(
                        "ownershipMoreThan5PercentOnBehalfOfAnotherPerson",
                        "Clients",
                        21,
                        28,
                        "Clients",
                    ),
                ),
            ),
            NarrativeItem(
                7,
                "Item 7",
                "Exhibit A",
                31,
                40,
                parsed_fields=(
                    NarrativeField(
                        "subsidiaryIdentificationAndClassification",
                        "Exhibit A",
                        31,
                        40,
                        "Exhibit A",
                    ),
                ),
            ),
            NarrativeItem(
                8,
                "Item 8",
                "Exhibit B",
                41,
                50,
                parsed_fields=(
                    NarrativeField(
                        "identificationAndClassificationOfGroupMembers",
                        "Exhibit B",
                        41,
                        50,
                        "Exhibit B",
                    ),
                ),
            ),
            NarrativeItem(
                9,
                "Item 9",
                "Dissolution",
                51,
                60,
                parsed_fields=(
                    NarrativeField(
                        "groupDissolutionNotice", "Dissolution", 51, 60, "Dissolution"
                    ),
                ),
            ),
        ),
        submission_type="SCHEDULE 13G",
        form_family="13G",
    )
    output = build_schedule13d_xml(doc)
    root = ET.fromstring(output.content)
    ns = {"s": SCHEDULE_13G_XML_NAMESPACE}
    assert root.findtext(".//s:item3/s:notApplicableFlag", namespaces=ns) == "Y"
    assert (
        root.findtext(".//s:item5/s:classOwnership5PercentOrLess", namespaces=ns) == "Y"
    )
    assert (
        root.findtext(
            ".//s:item6/s:ownershipMoreThan5PercentOnBehalfOfAnotherPerson",
            namespaces=ns,
        )
        == "Clients"
    )
    assert (
        root.findtext(
            ".//s:item7/s:subsidiaryIdentificationAndClassification", namespaces=ns
        )
        == "Exhibit A"
    )
    assert (
        root.findtext(
            ".//s:item8/s:identificationAndClassificationOfGroupMembers", namespaces=ns
        )
        == "Exhibit B"
    )
    assert (
        root.findtext(".//s:item9/s:groupDissolutionNotice", namespaces=ns)
        == "Dissolution"
    )


def test_signature_reporting_person_resolution_fallback() -> None:
    """Verify single filer and 1:1 index fallback for corporate signatories."""
    person = ReportingPersonCover(
        (
            CoverItemEvidence(
                1,
                "Name",
                "AVI MANAGEMENT LLC",
                EvidenceState.VALUE,
                tag="reportingPersonName",
            ),
        )
    )
    doc_13d = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(event_date="2024-01-02"),
        reporting_persons=(person,),
        signature_block=SignatureBlock(
            (Signatory(name="Darren C. Wallis", title="Manager", date="2024-01-02"),)
        ),
        submission_type="SCHEDULE 13D",
        form_family="13D",
    )
    out_13d = build_schedule13d_xml(doc_13d)
    root_13d = ET.fromstring(out_13d.content)
    ns_13d = {"s": SCHEDULE_13D_XML_NAMESPACE}
    assert (
        root_13d.findtext(
            ".//s:signatureInfo/s:signaturePerson/s:signatureReportingPerson",
            namespaces=ns_13d,
        )
        == "AVI MANAGEMENT LLC"
    )

    doc_13g = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(event_date="2024-01-02"),
        reporting_persons=(person,),
        signature_block=SignatureBlock(
            (Signatory(name="Darren C. Wallis", title="Manager", date="2024-01-02"),)
        ),
        submission_type="SCHEDULE 13G",
        form_family="13G",
    )
    out_13g = build_schedule13d_xml(doc_13g)
    root_13g = ET.fromstring(out_13g.content)
    ns_13g = {"s": SCHEDULE_13G_XML_NAMESPACE}
    assert (
        root_13g.findtext(
            ".//s:signatureInformation/s:reportingPersonName",
            namespaces=ns_13g,
        )
        == "AVI MANAGEMENT LLC"
    )


def test_schedule13g_item1_and_item2_fallback_to_document_metadata() -> None:
    """Verify Item 1 and Item 2 fallback to document issuer and person metadata."""
    person = ReportingPersonCover(
        (
            CoverItemEvidence(
                1,
                "Name",
                "Alpha Fund LP",
                EvidenceState.VALUE,
                tag="reportingPersonName",
            ),
            CoverItemEvidence(
                4,
                "Citizenship",
                "DE",
                EvidenceState.VALUE,
                tag="citizenshipOrOrganization",
            ),
        )
    )
    doc = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(
            issuer_name="Target Corp",
            event_date="2024-01-02",
            issuer_address=AddressDetails("100 Main St, City, ST 12345"),
        ),
        reporting_persons=(person,),
        narrative_items=(
            NarrativeItem(1, "Item 1", "", 0, 10),
            NarrativeItem(2, "Item 2", "", 11, 20),
        ),
        submission_type="SCHEDULE 13G",
        form_family="13G",
    )
    output = build_schedule13d_xml(doc)
    root = ET.fromstring(output.content)
    ns = {"s": SCHEDULE_13G_XML_NAMESPACE}
    assert root.findtext(".//s:item1/s:issuerName", namespaces=ns) == "Target Corp"
    assert (
        root.findtext(
            ".//s:item1/s:issuerPrincipalExecutiveOfficeAddress", namespaces=ns
        )
        == "100 Main St, City, ST 12345"
    )
    assert (
        root.findtext(".//s:item2/s:filingPersonName", namespaces=ns) == "Alpha Fund LP"
    )
    assert root.findtext(".//s:item2/s:citizenship", namespaces=ns) == "DE"


def test_schedule13g_items_substantive_not_applicable_flag_is_no() -> None:
    """Verify items 3, 5-10 with substantive content emit notApplicableFlag N."""
    person = ReportingPersonCover(
        (
            CoverItemEvidence(
                1, "Name", "Fund LP", EvidenceState.VALUE, tag="reportingPersonName"
            ),
        )
    )
    doc = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(event_date="2024-01-02"),
        reporting_persons=(person,),
        narrative_items=(
            NarrativeItem(
                3,
                "Item 3",
                "IA",
                0,
                10,
                parsed_fields=(
                    NarrativeField("typeOfReportingPerson", "IA, HC", 0, 6, "IA, HC"),
                ),
            ),
            NarrativeItem(
                5,
                "Item 5",
                "Ceased",
                11,
                20,
                parsed_fields=(
                    NarrativeField("is5PercentCessation", "Y", 11, 15, "Y"),
                ),
            ),
            NarrativeItem(
                10,
                "Item 10",
                "Cert",
                21,
                30,
                parsed_fields=(
                    NarrativeField(
                        "certifications", "Standard cert", 21, 30, "Standard cert"
                    ),
                ),
            ),
        ),
        signature_block=SignatureBlock((Signatory(name="Jane Doe"),)),
        submission_type="SCHEDULE 13G",
        form_family="13G",
    )
    output = build_schedule13d_xml(doc)
    root = ET.fromstring(output.content)
    ns = {"s": SCHEDULE_13G_XML_NAMESPACE}
    assert root.findtext(".//s:item3/s:notApplicableFlag", namespaces=ns) == "N"
    assert [
        e.text for e in root.findall(".//s:item3/s:typeOfPersonFiling", namespaces=ns)
    ] == ["IA", "HC"]
    assert root.findtext(".//s:item5/s:notApplicableFlag", namespaces=ns) == "N"
    assert (
        root.findtext(".//s:item5/s:classOwnership5PercentOrLess", namespaces=ns) == "Y"
    )
    assert root.findtext(".//s:item10/s:notApplicableFlag", namespaces=ns) == "N"
    assert (
        root.findtext(".//s:item10/s:certifications", namespaces=ns) == "Standard cert"
    )
    assert (
        root.findtext(".//s:signatureDetails/s:title", namespaces=ns)
        == "Authorized Signatory"
    )
    assert root.findtext(".//s:signatureDetails/s:date", namespaces=ns) == "01-02-2024"


def test_signature_details_inherits_block_date_and_ordinal_date() -> None:
    """Verify signatories without dates inherit block date and ordinal clauses normalize."""
    document = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(event_date="9/8/08"),
        reporting_persons=(),
        signature_block=SignatureBlock(
            (
                Signatory(
                    "Signer One",
                    date="executed on their behalf this 27th day of January, 2003.",
                ),
                Signatory("Signer Two", date=None),
            )
        ),
    )

    output = build_schedule13d_xml(document)
    root = ET.fromstring(output.content)
    dates = [
        e.text for e in root.findall(".//{http://www.sec.gov/edgar/schedule13D}date")
    ]
    assert dates == ["01-27-2003", "01-27-2003"]


def test_13g_jurisdiction_ignores_noise_tokens() -> None:
    document = BeneficialOwnershipDocument(
        submission_type="SCHEDULE 13G",
        issuer=IssuerMetadata(),
        reporting_persons=(
            ReportingPersonCover(
                (
                    CoverItemEvidence(1, "Name", "Entity", EvidenceState.VALUE),
                    CoverItemEvidence(4, "Citizenship", "OF", EvidenceState.VALUE),
                )
            ),
        ),
    )
    output = build_beneficial_ownership_xml(document)
    unparsed = json.loads(output.sidecars[0].content)["unparsed_sections"]
    assert not any(rec.get("status") == "unresolved" for rec in unparsed)
