import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.common.signatures import SignatureBlock, Signatory
from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    AddressDetails,
    BeneficialOwnershipDocument,
    CoverItemEvidence,
    EvidenceState,
    IssuerMetadata,
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

    root = ET.fromstring(build_schedule13d_xml(document))
    ns = {"s": SCHEDULE_13D_NS, "com": "http://www.sec.gov/edgar/common"}

    assert root.findtext("s:schemaVersion", namespaces=ns) == "X0202"
    assert (
        root.findtext("s:previousAccessionNumber", namespaces=ns)
        == "0000000000-26-000001"
    )
    assert (
        root.findtext("s:headerData/s:submissionType", namespaces=ns)
        == "SCHEDULE 13D/A"
    )
    assert root.findtext(".//s:issuerCusipNumber", namespaces=ns) == "1234567890123"
    assert root.findtext(".//s:memberOfGroup", namespaces=ns) == "b"
    assert root.findtext(".//com:street1", namespaces=ns) == "123 Main St"
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
        root.findtext(".//s:item4/s:transactionPurpose", namespaces=ns) == "Buy & hold."
    )
    assert (
        root.findtext(".//s:signatureDetails/s:signature", namespaces=ns)
        == "Ada Signer"
    )
