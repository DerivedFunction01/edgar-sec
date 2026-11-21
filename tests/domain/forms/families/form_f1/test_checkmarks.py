from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import STATUTORY_CHECKBOX_CONSTRAINTS
from edgar_sec.domain.forms.families.form_f1.checkmarks import (
    FORM_F1_CHECKBOX_SCHEMA,
    FORM_F2_CHECKBOX_SCHEMA,
)


def test_form_f1_checkbox_schema_properties() -> None:
    assert FORM_F1_CHECKBOX_SCHEMA.family == "F-1"
    assert FORM_F1_CHECKBOX_SCHEMA.groups == ("filer_status", "statutory_binary")
    assert FORM_F1_CHECKBOX_SCHEMA.constraints == STATUTORY_CHECKBOX_CONSTRAINTS


def test_form_f1_checkbox_schema_labels() -> None:
    keys = [label.key for label in FORM_F1_CHECKBOX_SCHEMA.labels]
    # The emerging-growth-company lines ride the common labels.
    assert "emerging_growth_company" in keys
    assert "egc_transition_optout" in keys
    assert keys[-3:] == ["rule_415", "rule_462b", "rule_462c"]
    for label in FORM_F1_CHECKBOX_SCHEMA.labels:
        assert label.phrases


def test_form_f2_checkbox_schema_adds_rule_434() -> None:
    assert FORM_F2_CHECKBOX_SCHEMA.family == "F-2"
    assert FORM_F2_CHECKBOX_SCHEMA.groups == FORM_F1_CHECKBOX_SCHEMA.groups
    assert FORM_F2_CHECKBOX_SCHEMA.constraints == STATUTORY_CHECKBOX_CONSTRAINTS
    keys = [label.key for label in FORM_F2_CHECKBOX_SCHEMA.labels]
    assert keys[-4:] == ["rule_415", "rule_462b", "rule_462c", "rule_434"]
    by_key = {label.key: label for label in FORM_F2_CHECKBOX_SCHEMA.labels}
    assert "rule 434" in by_key["rule_434"].phrases
