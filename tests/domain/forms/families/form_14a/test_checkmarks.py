from __future__ import annotations

from edgar_sec.domain.forms.families.form_14a.checkmarks import (
    FORM_14A_CHECKBOX_SCHEMA,
)


def test_form_14a_checkbox_schema_properties() -> None:
    assert FORM_14A_CHECKBOX_SCHEMA.family == "14A"
    assert FORM_14A_CHECKBOX_SCHEMA.groups == ("statutory_binary",)
    assert FORM_14A_CHECKBOX_SCHEMA.constraints == ()


def test_form_14a_checkbox_schema_labels() -> None:
    keys = [label.key for label in FORM_14A_CHECKBOX_SCHEMA.labels]
    assert keys == [
        "filed_by_registrant",
        "filed_by_other_party",
        "classification_preliminary",
        "classification_confidential",
        "classification_definitive",
        "classification_definitive_additional",
        "classification_soliciting_material",
        "fee_not_required",
        "fee_paid_previously",
        "fee_computed_on_table",
    ]
    for label in FORM_14A_CHECKBOX_SCHEMA.labels:
        assert label.group == "statutory_binary"
        assert label.phrases
    by_key = {label.key: label for label in FORM_14A_CHECKBOX_SCHEMA.labels}
    assert "preliminary information statement" in (
        by_key["classification_preliminary"].phrases
    )
    assert "definitive information statement" in (
        by_key["classification_definitive"].phrases
    )
