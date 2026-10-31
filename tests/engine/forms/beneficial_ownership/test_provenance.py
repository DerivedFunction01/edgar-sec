from __future__ import annotations

from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    BeneficialOwnershipDocument,
    IssuerMetadata,
    NarrativeItem,
)
from edgar_sec.engine.forms.beneficial_ownership.provenance import (
    build_field_extractions,
    build_unparsed_sections,
)


def test_field_extractions_and_unparsed_sections_cover_normalized_text() -> None:
    source = "Title: Common Stock\nItem 1. Common Stock details\nLoose residue."
    item_start = source.index("Item 1.")
    doc = BeneficialOwnershipDocument(
        issuer=IssuerMetadata(security_class="Common Stock"),
        reporting_persons=(),
        narrative_items=(
            NarrativeItem(
                number=1,
                heading="Item 1.",
                text="Common Stock details",
                start_offset=item_start,
                end_offset=source.index("\nLoose"),
            ),
        ),
    )

    extractions = build_field_extractions(doc, source, len("Title: Common Stock"))
    unparsed = build_unparsed_sections(source, extractions)

    assert [item.field_path for item in extractions] == [
        "formData.coverPageHeader.securitiesClassTitle",
        "formData.items1To7.item1.commentText",
    ]
    mapped = {
        index
        for item in extractions
        for index in range(item.start_offset, item.end_offset)
    }
    residual = {
        index
        for item in unparsed
        for index in range(item.start_offset, item.end_offset)
    }
    assert all(
        source[index].isspace() or index in mapped or index in residual
        for index in range(len(source))
    )
    assert all(
        item.source_text == source[item.start_offset : item.end_offset]
        for item in extractions
    )
    assert any("Loose residue." in item.text for item in unparsed)
