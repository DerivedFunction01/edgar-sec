from __future__ import annotations

from edgar_sec.domain.forms.families.form_sd.taxonomy import FORM_SD_ITEMS, SD_TITLES


def test_four_item_taxonomy_in_section_order() -> None:
    assert [d.item for d in FORM_SD_ITEMS] == [
        "ITEM 1.01",
        "ITEM 1.02",
        "ITEM 2.01",
        "ITEM 3.01",
    ]
    assert [d.part for d in FORM_SD_ITEMS] == [1, 1, 2, 3]


def test_item_2_01_carries_both_printed_titles() -> None:
    names = FORM_SD_ITEMS[2].names
    assert "Resource Extraction Issuer Disclosure and Report" in names
    assert "Resource Extraction Issuer Disclosure Report" in names


def test_titles_name_the_form() -> None:
    assert "specialized disclosure report" in SD_TITLES
