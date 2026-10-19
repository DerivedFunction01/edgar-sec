from __future__ import annotations

from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    BeneficialOwnershipDocument,
    CoverItemEvidence,
    EvidenceState,
    IssuerMetadata,
    NarrativeItem,
    ReportingPersonCover,
)


def test_reporting_person_cover_retrieval_by_number_and_tag() -> None:
    items = (
        CoverItemEvidence(
            number=1,
            source_text="Alice Corp",
            value="Alice Corp",
            state=EvidenceState.VALUE,
            tag="reportingPersonName",
        ),
        CoverItemEvidence(
            number=6,
            source_text="Delaware",
            value="Delaware",
            state=EvidenceState.VALUE,
            tag="citizenshipOrOrganization",
        ),
    )
    person = ReportingPersonCover(items=items)
    assert person.first_item(1) is items[0]
    assert person.first_item("reportingPersonName") is items[0]
    assert person.first_item(6) is items[1]
    assert person.first_item("citizenshipOrOrganization") is items[1]
    assert person.first_item("nonexistent") is None
    assert person.first_item(99) is None


def test_beneficial_ownership_document_items1_to_7_property() -> None:
    items = tuple(
        NarrativeItem(
            number=i,
            heading=f"Item {i}",
            text=f"Body {i}",
            start_offset=0,
            end_offset=10,
        )
        for i in range(1, 11)
    )
    doc = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(issuer_name="Test Inc"),
        reporting_persons=(),
        narrative_items=items,
    )
    assert len(doc.narrative_items) == 10
    assert len(doc.items1_to_7) == 7
    assert tuple(it.number for it in doc.items1_to_7) == (1, 2, 3, 4, 5, 6, 7)
