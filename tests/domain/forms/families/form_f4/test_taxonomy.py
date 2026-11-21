from __future__ import annotations

from edgar_sec.domain.forms.families.form_f4.taxonomy import FORM_F4_ITEMS


def test_form_f4_taxonomy_items() -> None:
    keys = [d.item for d in FORM_F4_ITEMS]
    assert keys == [
        "PROSPECTUS SUMMARY",
        "RISK FACTORS",
        "TERMS OF THE TRANSACTION",
        "PRO FORMA FINANCIAL INFORMATION",
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
        "ITEM 20",
        "ITEM 21",
        "ITEM 22",
        "ITEM 16",
    ]
    for definition in FORM_F4_ITEMS:
        assert definition.names


def test_form_f4_part_ii_items() -> None:
    part_two = {d.item: d for d in FORM_F4_ITEMS if d.part == 2}
    assert part_two["ITEM 20"].names == ("indemnification of directors and officers",)
    assert "exhibits and financial statement schedules" in part_two["ITEM 21"].names
    assert part_two["ITEM 22"].names == ("undertakings",)
    # The older-POS Item 16 Exhibits numbering is an optional era variant.
    assert part_two["ITEM 16"].optional is True


def test_form_f4_transaction_names_are_grounded_variants() -> None:
    by_item = {d.item: d.names for d in FORM_F4_ITEMS}
    assert "the merger" in by_item["TERMS OF THE TRANSACTION"]
    assert (
        "unaudited pro forma financial information"
        in (by_item["PRO FORMA FINANCIAL INFORMATION"])
    )
