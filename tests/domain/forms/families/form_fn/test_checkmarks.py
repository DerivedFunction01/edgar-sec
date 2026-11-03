from __future__ import annotations

from edgar_sec.domain.forms.families.form_fn.checkmarks import (
    FORM_FN_CHECKBOX_SCHEMA,
)


def test_form_fn_checkbox_schema_is_marks_only() -> None:
    assert FORM_FN_CHECKBOX_SCHEMA.family == "F-N"
    assert FORM_FN_CHECKBOX_SCHEMA.groups == ("statutory_binary",)
    keys = [label.key for label in FORM_FN_CHECKBOX_SCHEMA.labels]
    assert keys == ["original_filing", "amended_filing"]
    for label in FORM_FN_CHECKBOX_SCHEMA.labels:
        assert label.phrases


def test_form_fn_filing_kind_is_exclusive() -> None:
    names = [c.name for c in FORM_FN_CHECKBOX_SCHEMA.constraints]
    assert names == ["filing_kind_exclusion"]
    constraint = FORM_FN_CHECKBOX_SCHEMA.constraints[0]
    assert constraint.relation == "not_both"
    assert constraint.left == "original_filing"
    assert constraint.right == "amended_filing"
