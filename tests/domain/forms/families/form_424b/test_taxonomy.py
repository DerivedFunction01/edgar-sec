from __future__ import annotations

from edgar_sec.domain.forms.families.form_424b.taxonomy import (
    FORM_424B_DOCUMENT_KINDS,
    FORM_424B_ITEMS,
    FORM_424B_TITLES,
)


def test_form_424b_taxonomy_items() -> None:
    keys = [d.item for d in FORM_424B_ITEMS]
    assert keys == [
        "ABOUT THIS PROSPECTUS",
        "PROSPECTUS SUMMARY",
        "FORWARD-LOOKING STATEMENTS",
        "RISK FACTORS",
        "RATIO OF EARNINGS TO FIXED CHARGES",
        "THE OFFERING",
        "USE OF PROCEEDS",
        "SELLING STOCKHOLDERS",
        "PLAN OF DISTRIBUTION",
        "UNDERWRITING",
        "DESCRIPTION OF SECURITIES",
        "OUR COMPANY",
        "TAX CONSIDERATIONS",
        "LEGAL MATTERS",
        "EXPERTS",
        "INCORPORATION BY REFERENCE",
        "WHERE YOU CAN FIND MORE INFORMATION",
    ]
    for definition in FORM_424B_ITEMS:
        assert definition.names
        assert definition.part == 1


def test_form_424b_taxonomy_names_are_grounded_variants() -> None:
    by_item = {d.item: d.names for d in FORM_424B_ITEMS}
    assert "selected risk considerations" in by_item["RISK FACTORS"]
    assert "selling securityholders" in by_item["SELLING STOCKHOLDERS"]
    assert "prospectus supplement summary" in by_item["PROSPECTUS SUMMARY"]
    assert "about this prospectus supplement" in by_item["ABOUT THIS PROSPECTUS"]


def test_form_424b_document_kinds_are_most_specific_first() -> None:
    keys = [key for key, _ in FORM_424B_DOCUMENT_KINDS]
    assert keys == [
        "pricing_supplement",
        "preliminary_prospectus_supplement",
        "prospectus_supplement",
        "preliminary_prospectus",
        "prospectus",
    ]
    for _, phrases in FORM_424B_DOCUMENT_KINDS:
        assert phrases


def test_form_424b_titles() -> None:
    assert "prospectus" in FORM_424B_TITLES
    assert "pricing supplement" in FORM_424B_TITLES
