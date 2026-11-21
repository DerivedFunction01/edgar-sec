from __future__ import annotations

from edgar_sec.domain.forms.families.form_fn.taxonomy import (
    FORM_FN_ITEMS,
    FORM_FN_LETTERED_ITEMS,
    FORM_FN_TITLES,
)


def test_form_fn_has_no_item_taxonomy() -> None:
    assert FORM_FN_ITEMS == ()
    assert "appointment of agent for service of process" in FORM_FN_TITLES


def test_form_fn_lettered_items_are_the_printed_form_fields() -> None:
    letters = [letter for letter, _ in FORM_FN_LETTERED_ITEMS]
    assert letters == ["A", "B", "C", "D", "E", "F", "G"]
    by_letter = dict(FORM_FN_LETTERED_ITEMS)
    assert by_letter["A"] == "name of issuer or person filing"
    assert by_letter["B"] == "this is (select one)"
    assert "agent for service of process" in by_letter["E"]
