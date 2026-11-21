from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import STATUTORY_CHECKBOX_CONSTRAINTS
from edgar_sec.domain.forms.families.form_f4.checkmarks import (
    FORM_F4_CHECKBOX_SCHEMA,
)


def test_form_f4_checkbox_schema_properties() -> None:
    assert FORM_F4_CHECKBOX_SCHEMA.family == "F-4"
    assert FORM_F4_CHECKBOX_SCHEMA.groups == ("filer_status", "statutory_binary")
    assert FORM_F4_CHECKBOX_SCHEMA.constraints == STATUTORY_CHECKBOX_CONSTRAINTS


def test_form_f4_checkbox_schema_labels() -> None:
    keys = [label.key for label in FORM_F4_CHECKBOX_SCHEMA.labels]
    assert "emerging_growth_company" in keys
    assert "egc_transition_optout" in keys
    assert keys[-3:] == ["rule_415", "rule_462b", "rule_462c"]
    for label in FORM_F4_CHECKBOX_SCHEMA.labels:
        assert label.phrases
