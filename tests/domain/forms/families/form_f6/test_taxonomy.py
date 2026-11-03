from __future__ import annotations

from edgar_sec.domain.forms.families.form_f6.taxonomy import FORM_F6_ITEMS


def test_form_f6_taxonomy_items() -> None:
    keys = [(d.item, d.part) for d in FORM_F6_ITEMS]
    assert keys == [
        ("ITEM 1", 1),
        ("ITEM 2", 1),
        ("ITEM 3", 2),
        ("ITEM 4", 2),
        ("ITEM 1", 2),
        ("ITEM 2", 2),
    ]
    part_one = {d.item: d for d in FORM_F6_ITEMS if d.part == 1}
    assert part_one["ITEM 1"].names == ("description of securities to be registered",)
    assert part_one["ITEM 2"].names == ("available information",)


def test_form_f6_part_ii_numbering_variants() -> None:
    canonical = {d.item: d for d in FORM_F6_ITEMS if d.part == 2 and not d.optional}
    assert canonical["ITEM 3"].names[0] == "exhibits"
    assert canonical["ITEM 4"].names == ("undertakings",)
    variant = {d.item: d for d in FORM_F6_ITEMS if d.part == 2 and d.optional}
    assert variant["ITEM 1"].names[0] == "exhibits"
    assert variant["ITEM 2"].names == ("undertakings",)
