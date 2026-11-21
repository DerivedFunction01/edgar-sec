from __future__ import annotations

from edgar_sec.domain.forms.families.form_f6.checkmarks import (
    FORM_F6_CHECKBOX_SCHEMA,
)


def test_form_f6_checkbox_schema_properties() -> None:
    assert FORM_F6_CHECKBOX_SCHEMA.family == "F-6"
    assert FORM_F6_CHECKBOX_SCHEMA.groups == ("statutory_binary",)
    names = [c.name for c in FORM_F6_CHECKBOX_SCHEMA.constraints]
    assert names == ["rule_466_election_exclusion"]


def test_form_f6_checkbox_schema_labels() -> None:
    keys = [label.key for label in FORM_F6_CHECKBOX_SCHEMA.labels]
    assert keys == [
        "rule_466_immediate",
        "rule_466_deferred",
        "separate_registration_statement",
    ]
    for label in FORM_F6_CHECKBOX_SCHEMA.labels:
        assert label.phrases
    constraint = FORM_F6_CHECKBOX_SCHEMA.constraints[0]
    assert constraint.relation == "not_both"
    assert constraint.left == "rule_466_immediate"
    assert constraint.right == "rule_466_deferred"
