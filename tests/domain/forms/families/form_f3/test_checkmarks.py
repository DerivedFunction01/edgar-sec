from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import STATUTORY_CHECKBOX_CONSTRAINTS
from edgar_sec.domain.forms.families.form_f3.checkmarks import (
    FORM_F3_CHECKBOX_SCHEMA,
)


def test_form_f3_checkbox_schema_properties() -> None:
    assert FORM_F3_CHECKBOX_SCHEMA.family == "F-3"
    assert FORM_F3_CHECKBOX_SCHEMA.groups == ("filer_status", "statutory_binary")
    assert FORM_F3_CHECKBOX_SCHEMA.constraints == STATUTORY_CHECKBOX_CONSTRAINTS


def test_form_f3_checkbox_schema_labels() -> None:
    keys = [label.key for label in FORM_F3_CHECKBOX_SCHEMA.labels]
    assert "emerging_growth_company" in keys
    assert keys[-6:] == [
        "rule_415",
        "rule_462b",
        "rule_462c",
        "rule_462e",
        "drip",
        "general_instruction_ic",
    ]
    for label in FORM_F3_CHECKBOX_SCHEMA.labels:
        assert label.phrases
    by_key = {label.key: label for label in FORM_F3_CHECKBOX_SCHEMA.labels}
    assert "dividend reinvestment plan" in by_key["drip"].phrases
    assert "general instruction i.c." in by_key["general_instruction_ic"].phrases
    assert "rule 462(e)" in by_key["rule_462e"].phrases
