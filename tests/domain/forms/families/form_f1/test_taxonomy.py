from __future__ import annotations

from edgar_sec.domain.forms.families.form_f1.taxonomy import (
    FORM_F1_ITEMS,
    FORM_F2_ITEMS,
)

_PROSPECTUS_KEYS = [
    "PROSPECTUS SUMMARY",
    "RISK FACTORS",
    "USE OF PROCEEDS",
    "DETERMINATION OF OFFERING PRICE",
    "DIVIDEND POLICY",
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
]


def test_form_f1_taxonomy_items() -> None:
    keys = [d.item for d in FORM_F1_ITEMS]
    assert keys == [*_PROSPECTUS_KEYS, "ITEM 6", "ITEM 7", "ITEM 8", "ITEM 9"]
    for definition in FORM_F1_ITEMS:
        assert definition.names
    part_two = {d.item: d for d in FORM_F1_ITEMS if d.part == 2}
    assert part_two["ITEM 6"].names == ("indemnification of directors and officers",)
    assert "recent sales of unregistered securities" in part_two["ITEM 7"].names
    assert "exhibits and financial statement schedules" in part_two["ITEM 8"].names
    assert part_two["ITEM 9"].names == ("undertakings",)


def test_form_f1_prospectus_names_are_grounded_variants() -> None:
    by_item = {d.item: d.names for d in FORM_F1_ITEMS}
    assert "selling security holders" in by_item["SELLING SHAREHOLDERS"]
    assert "description of capital stock" in by_item["DESCRIPTION OF SECURITIES"]
    assert "canadian tax considerations" in by_item["TAX CONSIDERATIONS"]
    assert (
        "incorporation of certain information by reference"
        in (by_item["INCORPORATION BY REFERENCE"])
    )


def test_form_f2_taxonomy_carries_both_part_ii_numberings() -> None:
    keys = [d.item for d in FORM_F2_ITEMS]
    assert keys == [
        *_PROSPECTUS_KEYS,
        "ITEM 8",
        "ITEM 9",
        "ITEM 10",
        "ITEM 14",
        "ITEM 15",
        "ITEM 16",
        "ITEM 17",
    ]
    by_item = {d.item: d for d in FORM_F2_ITEMS if d.part == 2}
    assert by_item["ITEM 8"].names == ("indemnification of directors and officers",)
    assert by_item["ITEM 9"].names[0] == "exhibits"
    assert by_item["ITEM 10"].names == ("undertakings",)
    # The S-1-numbered era variant is recorded as optional.
    for key in ("ITEM 14", "ITEM 15", "ITEM 16", "ITEM 17"):
        assert by_item[key].optional is True
    assert "recent sales of unregistered securities" in by_item["ITEM 15"].names
