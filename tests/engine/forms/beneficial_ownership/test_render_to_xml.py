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
from edgar_sec.engine.forms.beneficial_ownership.render_to_xml import (
    SCHEDULE_13D_NS,
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
    ns = {"s": SCHEDULE_13D_NS, "com": "http://www.sec.gov/edgar/common"}

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
        "00",
        "WC",
        "PF",
        "00",
        "WC",
        "PF",
    ]
    assert [node.text for node in root.findall(".//s:typeOfReportingPerson", ns)] == [
        "IN",
        "OO",
        "00",
        "IN",
        "OO",
        "00",
    ]
    assert len(root.findall(".//s:reportingPersonInfo", ns)) == 2
    assert len(root.findall(".//s:commentContent", ns)) == 2
    assert root.findtext(".//s:legalProceedings", namespaces=ns) == "Y"
    assert (
        root.findtext(".//s:Item4/s:transactionPurpose", namespaces=ns) == "Buy & hold."
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
    namespace = {"s": "http://www.sec.gov/edgar/schedule13G"}

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
    assert root.find(".//s:items", namespace) is None
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
    ns = {"s": "http://www.sec.gov/edgar/schedule13G"}
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
    ns = {"s": "http://www.sec.gov/edgar/schedule13G"}
    assert (
        root.findtext(".//s:Item4/s:amountBeneficiallyOwned", namespaces=ns) == "500000"
    )
    assert root.findtext(".//s:Item4/s:classPercent", namespaces=ns) == "5.5"
    assert (
        root.findtext(
            ".//s:Item4/s:numberOfSharesPersonHas/s:solePowerOrDirectToVote",
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
    ns = {"s": "http://www.sec.gov/edgar/schedule13G"}
    assert (
        root.findtext(".//s:Item10/s:certifications", namespaces=ns)
        == "Securities not acquired for control purposes."
    )
