from __future__ import annotations

from edgar_sec.domain.forms.families.form_40f.taxonomy import (
    FORM_40F_FURNISHED_KINDS,
    FORM_40F_ITEMS,
    FORM_40F_TITLES,
)


def test_form_40f_has_no_item_taxonomy() -> None:
    assert FORM_40F_ITEMS == ()
    assert FORM_40F_TITLES == ("form 40-f",)


def test_form_40f_furnished_kinds() -> None:
    assert list(FORM_40F_FURNISHED_KINDS) == [
        "aif",
        "financial_statements",
        "mda",
        "other_exhibits",
    ]
    assert FORM_40F_FURNISHED_KINDS["aif"] == ("annual information form",)
    assert (
        "audited annual financial statements"
        in (FORM_40F_FURNISHED_KINDS["financial_statements"])
    )
    assert "management's discussion and analysis" in FORM_40F_FURNISHED_KINDS["mda"]
