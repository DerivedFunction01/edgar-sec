from __future__ import annotations

from edgar_sec.domain.forms.families.form_11k.checkmarks import (
    FORM_11K_CHECKBOX_SCHEMA,
)


def test_form_11k_checkbox_schema_properties() -> None:
    assert FORM_11K_CHECKBOX_SCHEMA.family == "11-K"
    assert FORM_11K_CHECKBOX_SCHEMA.groups == ("statutory_binary",)
    assert FORM_11K_CHECKBOX_SCHEMA.constraints == ()
    assert FORM_11K_CHECKBOX_SCHEMA.report_period_companion == "report_annual"
    assert FORM_11K_CHECKBOX_SCHEMA.report_period_transition == "report_transition"


def test_form_11k_checkbox_schema_labels() -> None:
    keys = [label.key for label in FORM_11K_CHECKBOX_SCHEMA.labels]
    assert keys == ["report_annual", "report_transition"]
    for label in FORM_11K_CHECKBOX_SCHEMA.labels:
        assert label.group == "statutory_binary"
        assert label.phrases
        assert "section 15(d)" in label.phrases[0]
        assert any("section 15-(d)" in phrase for phrase in label.phrases)
