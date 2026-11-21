from __future__ import annotations

from edgar_sec.domain.forms.families.form_f3.taxonomy import FORM_F3_ITEMS


def test_form_f3_taxonomy_items() -> None:
    keys = [d.item for d in FORM_F3_ITEMS]
    assert keys == [
        "PROSPECTUS SUMMARY",
        "RISK FACTORS",
        "USE OF PROCEEDS",
        "CAPITALIZATION",
        "DILUTION",
        "SELLING SHAREHOLDERS",
        "PLAN OF DISTRIBUTION",
        "UNDERWRITING",
        "DESCRIPTION OF SECURITIES",
        "ENFORCEABILITY OF CIVIL LIABILITIES",
        "EXCHANGE CONTROLS",
        "TAX CONSIDERATIONS",
        "LEGAL MATTERS",
        "EXPERTS",
        "INCORPORATION BY REFERENCE",
        "WHERE YOU CAN FIND MORE INFORMATION",
        "ITEM 8",
        "ITEM 9",
        "ITEM 10",
    ]
    for definition in FORM_F3_ITEMS:
        assert definition.names


def test_form_f3_part_ii_items() -> None:
    part_two = {d.item: d for d in FORM_F3_ITEMS if d.part == 2}
    assert part_two["ITEM 8"].names == ("indemnification of directors and officers",)
    # Filed specimens caption the exhibits item plainly, without schedules.
    assert part_two["ITEM 9"].names == (
        "exhibits",
        "index to exhibits",
        "exhibit index",
    )
    assert part_two["ITEM 10"].names == ("undertakings",)


def test_form_f3_incorporation_by_reference_is_core() -> None:
    by_item = {d.item: d for d in FORM_F3_ITEMS}
    # Shelf registration incorporates by reference; the item is not optional.
    assert by_item["INCORPORATION BY REFERENCE"].optional is False
    assert "incorporation of certain information by reference" in (
        by_item["INCORPORATION BY REFERENCE"].names
    )
