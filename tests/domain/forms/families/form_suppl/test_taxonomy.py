from __future__ import annotations

from edgar_sec.domain.forms.families.form_suppl.taxonomy import (
    FORM_SUPPL_BASE_FORMS,
    FORM_SUPPL_BASE_PROSPECTUS_PHRASES,
    FORM_SUPPL_INSTRUCTION_REFERENCES,
    FORM_SUPPL_ITEMS,
    FORM_SUPPL_KINDS,
)


def test_form_suppl_has_no_item_taxonomy() -> None:
    assert FORM_SUPPL_ITEMS == ()


def test_form_suppl_caption_keys() -> None:
    assert FORM_SUPPL_BASE_FORMS == ("F-9", "F-10")
    assert FORM_SUPPL_INSTRUCTION_REFERENCES == (
        "general instruction ii.k of form f-9",
        "general instruction ii.l of form f-10",
    )
    assert FORM_SUPPL_KINDS == (
        "prospectus supplement",
        "pricing supplement",
        "preliminary prospectus supplement",
        "preliminary pricing supplement",
    )
    assert "short form base shelf prospectus dated" in (
        FORM_SUPPL_BASE_PROSPECTUS_PHRASES
    )
