from __future__ import annotations

from edgar_sec.domain.forms.families.form_15.checkmarks import (
    FORM_15_CHECKBOX_SCHEMA,
)


def test_form_15_checkbox_schema_properties() -> None:
    assert FORM_15_CHECKBOX_SCHEMA.family == "15"
    assert FORM_15_CHECKBOX_SCHEMA.groups == ("statutory_binary",)
    assert FORM_15_CHECKBOX_SCHEMA.constraints == ()


def test_form_15_checkbox_schema_labels() -> None:
    keys = [label.key for label in FORM_15_CHECKBOX_SCHEMA.labels]
    assert keys == [
        "rule_12g4_a1",
        "rule_12g4_a2",
        "rule_12h3_b1_i",
        "rule_12h3_b1_ii",
        "rule_15d6",
    ]
    for label in FORM_15_CHECKBOX_SCHEMA.labels:
        assert label.group == "statutory_binary"
        assert label.phrases
        assert label.phrases[0].startswith("rule ")
