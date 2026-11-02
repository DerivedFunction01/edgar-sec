from __future__ import annotations

from edgar_sec.domain.forms.families.form_15.taxonomy import (
    FORM_15_ITEMS,
    FORM_15_TITLES,
)


def test_form_15_taxonomy_has_no_items() -> None:
    assert FORM_15_ITEMS == ()


def test_form_15_titles() -> None:
    assert "certification and notice of termination of registration" in FORM_15_TITLES
    assert "form 15" in FORM_15_TITLES
