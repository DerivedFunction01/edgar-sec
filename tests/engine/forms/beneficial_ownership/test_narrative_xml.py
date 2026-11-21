"""Tests for beneficial ownership narrative XML rendering."""

from __future__ import annotations

import xml.etree.ElementTree as ET

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
from edgar_sec.engine.forms.beneficial_ownership.narrative_xml import (
    render_narrative_13d_xml,
    render_narrative_13g_xml,
)


def test_render_narrative_13d_xml_emits_comment_text() -> None:
    """Verify 13D narrative item serializes comment text."""
    parent = ET.Element("items1To7")
    item = NarrativeItem(
        number=1, heading="Item 1", text="Sample text", start_offset=0, end_offset=10
    )
    render_narrative_13d_xml(parent, item)
    elem = parent.find("item1")
    assert elem is not None
    assert elem.findtext("commentText") == "Sample text"


def test_render_narrative_13d_xml_emits_parsed_fields() -> None:
    """Verify 13D narrative item serializes parsed fields."""
    parent = ET.Element("items1To7")
    fields = (
        NarrativeField("transactionPurpose", "Growth capital", 0, 14, "Growth capital"),
    )
    item = NarrativeItem(
        number=4,
        heading="Item 4",
        text="",
        start_offset=0,
        end_offset=14,
        parsed_fields=fields,
    )
    render_narrative_13d_xml(parent, item)
    elem = parent.find("item4")
    assert elem is not None
    assert elem.findtext("transactionPurpose") == "Growth capital"


def test_render_narrative_13g_xml_handles_not_applicable_flag() -> None:
    """Verify 13G narrative items emit notApplicableFlag."""
    parent = ET.Element("items")
    unresolved: list[dict[str, object]] = []
    item = NarrativeItem(
        number=3,
        heading="Item 3",
        text="",
        start_offset=0,
        end_offset=0,
        parsed_fields=(NarrativeField("notApplicableFlag", "Y", 0, 0, ""),),
    )
    result = render_narrative_13g_xml(parent, item, unresolved)
    assert result is True
    elem = parent.find("item3")
    assert elem is not None
    assert elem.findtext("notApplicableFlag") == "Y"


def test_render_narrative_13g_xml_substantive_splits_codes() -> None:
    """Verify 13G Item 3 splits comma-separated reporting codes."""
    parent = ET.Element("items")
    unresolved: list[dict[str, object]] = []
    item = NarrativeItem(
        number=3,
        heading="Item 3",
        text="",
        start_offset=0,
        end_offset=0,
        parsed_fields=(NarrativeField("typeOfReportingPerson", "IA, HC", 0, 0, ""),),
    )
    result = render_narrative_13g_xml(parent, item, unresolved)
    assert result is True
    elem = parent.find("item3")
    assert elem is not None
    assert elem.findtext("notApplicableFlag") == "N"
    codes = [e.text for e in elem.findall("typeOfPersonFiling")]
    assert codes == ["IA", "HC"]


def test_render_narrative_13g_xml_drops_invalid_item3_codes() -> None:
    parent = ET.Element("items")
    item = NarrativeItem(
        number=3,
        heading="Item 3",
        text="",
        start_offset=0,
        end_offset=0,
        parsed_fields=(NarrativeField("typeOfReportingPerson", "IN, PN", 0, 0, ""),),
    )

    assert render_narrative_13g_xml(parent, item, []) is True
    item3 = parent.find("item3")
    assert item3 is not None
    assert item3.findtext("notApplicableFlag") == "Y"
    assert item3.findall("typeOfPersonFiling") == []


def test_render_narrative_13g_xml_keeps_item2_citizenship_text() -> None:
    parent = ET.Element("items")
    unresolved: list[dict[str, object]] = []
    item = NarrativeItem(
        number=2,
        heading="Item 2",
        text="",
        start_offset=0,
        end_offset=0,
        parsed_fields=(
            NarrativeField(
                "citizenshipOrOrganization",
                "Please refer to Item 4 on each cover sheet",
                0,
                0,
                "",
            ),
        ),
    )

    assert render_narrative_13g_xml(parent, item, unresolved) is True
    assert (
        parent.findtext("item2/citizenship")
        == "Please refer to Item 4 on each cover sheet"
    )
    assert unresolved == []


def test_render_narrative_13g_xml_item1_and_item2_doc_fallback() -> None:
    """Verify 13G Item 1 and Item 2 fallback to document metadata."""
    parent = ET.Element("items")
    unresolved: list[dict[str, object]] = []
    person = ReportingPersonCover(
        items=(
            CoverItemEvidence(
                1,
                "Name",
                "Fund LP",
                EvidenceState.VALUE,
                tag="reportingPersonName",
            ),
            CoverItemEvidence(
                4,
                "Cit",
                "DE",
                EvidenceState.VALUE,
                tag="citizenshipOrOrganization",
            ),
        )
    )
    doc = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(
            issuer_name="Acme Corp",
            issuer_address=AddressDetails("123 Main St"),
        ),
        reporting_persons=(person,),
    )
    item1 = NarrativeItem(
        number=1, heading="Item 1", text="", start_offset=0, end_offset=0
    )
    item2 = NarrativeItem(
        number=2, heading="Item 2", text="", start_offset=0, end_offset=0
    )
    assert render_narrative_13g_xml(parent, item1, unresolved, doc=doc) is True
    assert render_narrative_13g_xml(parent, item2, unresolved, doc=doc) is True
    assert parent.findtext("item1/issuerName") == "Acme Corp"
    assert (
        parent.findtext("item1/issuerPrincipalExecutiveOfficeAddress") == "123 Main St"
    )
    assert parent.findtext("item2/filingPersonName") == "Fund LP"
    assert parent.findtext("item2/citizenship") == "DE"


def test_render_narrative_13d_xml_item2_and_item5_doc_fallback() -> None:
    """Verify 13D Item 2 and Item 5 fallback to reporting person cover values."""
    parent = ET.Element("items1To7")
    person = ReportingPersonCover(
        items=(
            CoverItemEvidence(
                1, "Name", "Alpha Buyer", EvidenceState.VALUE, tag="reportingPersonName"
            ),
            CoverItemEvidence(
                6,
                "Cit",
                "Delaware",
                EvidenceState.VALUE,
                tag="citizenshipOrOrganization",
            ),
            CoverItemEvidence(
                9, "Shares", "500000", EvidenceState.VALUE, tag="aggregateAmountOwned"
            ),
            CoverItemEvidence(
                13, "Pct", "7.5", EvidenceState.VALUE, tag="percentOfClass"
            ),
        )
    )
    doc = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(), reporting_persons=(person,)
    )
    render_narrative_13d_xml(parent, NarrativeItem(2, "Item 2", "", 0, 0), doc=doc)
    render_narrative_13d_xml(parent, NarrativeItem(5, "Item 5", "", 0, 0), doc=doc)
    assert parent.findtext("item2/filingPersonName") == "Alpha Buyer"
    assert parent.findtext("item2/citizenship") == "Delaware"
    assert parent.findtext("item5/percentageOfClassSecurities") == "7.5"
    assert parent.findtext("item5/numberOfShares") == "500000"


def test_render_narrative_13g_xml_item4_doc_fallback() -> None:
    """Verify 13G Item 4 falls back to reporting person cover numbers."""
    parent = ET.Element("items")
    unresolved: list[dict[str, object]] = []
    person = ReportingPersonCover(
        items=(
            CoverItemEvidence(
                9,
                "Aggregate",
                "250000",
                EvidenceState.VALUE,
                tag="aggregateAmountOwned",
            ),
            CoverItemEvidence(
                11, "Percent", "6.2", EvidenceState.VALUE, tag="percentOfClass"
            ),
            CoverItemEvidence(
                5, "SoleVote", "200000", EvidenceState.VALUE, tag="soleVotingPower"
            ),
        )
    )
    doc = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(), reporting_persons=(person,)
    )
    assert (
        render_narrative_13g_xml(
            parent, NarrativeItem(4, "Item 4", "", 0, 0), unresolved, doc=doc
        )
        is True
    )
    assert parent.findtext("item4/amountBeneficiallyOwned") == "250000"
    assert parent.findtext("item4/classPercent") == "6.2"
    assert (
        parent.findtext("item4/numberOfSharesPersonHas/solePowerOrDirectToVote")
        == "200000"
    )


def test_render_narrative_13g_xml_item4_preserves_fractional_shares() -> None:
    parent = ET.Element("items")
    unresolved: list[dict[str, object]] = []
    item = NarrativeItem(
        number=4,
        heading="Item 4",
        text="",
        start_offset=0,
        end_offset=0,
        parsed_fields=(
            NarrativeField("aggregateAmountOwned", "14,195,929.7501", 0, 0, ""),
            NarrativeField("soleVotingPower", "14,195,929.7501", 0, 0, ""),
        ),
    )

    assert render_narrative_13g_xml(parent, item, unresolved) is True
    assert parent.findtext("item4/amountBeneficiallyOwned") == "14195929.7501"
    assert (
        parent.findtext("item4/numberOfSharesPersonHas/solePowerOrDirectToVote")
        == "14195929.7501"
    )
    assert unresolved == []


def test_render_narrative_13g_xml_item4_keeps_unresolved_text() -> None:
    parent = ET.Element("items")
    unresolved: list[dict[str, object]] = []
    item = NarrativeItem(
        number=4,
        heading="Item 4",
        text="",
        start_offset=0,
        end_offset=0,
        parsed_fields=(
            NarrativeField("aggregateAmountOwned", "None of the 500 shares", 0, 0, ""),
        ),
    )

    assert render_narrative_13g_xml(parent, item, unresolved) is True
    assert parent.findtext("item4/amountBeneficiallyOwned") == "None of the 500 shares"
    assert unresolved == []
