from __future__ import annotations

from edgar_sec.domain.forms.families.form_fwp.taxonomy import FORM_FWP_ITEMS


def test_form_fwp_taxonomy_items() -> None:
    keys = [d.item for d in FORM_FWP_ITEMS]
    assert keys == ["SUMMARY TERMS", "TAX CONSIDERATIONS"]
    by_item = {d.item: d.names for d in FORM_FWP_ITEMS}
    assert "key terms" in by_item["SUMMARY TERMS"]
    for definition in FORM_FWP_ITEMS:
        assert definition.names
        assert definition.part == 1
