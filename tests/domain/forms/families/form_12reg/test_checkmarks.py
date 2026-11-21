from __future__ import annotations

from edgar_sec.domain.forms.families.form_12reg.checkmarks import (
    FORM_25_CHECKBOX_SCHEMA,
    FORM_8A_CHECKBOX_SCHEMA,
)


def test_form_25_schema_covers_six_provisions() -> None:
    keys = [label.key for label in FORM_25_CHECKBOX_SCHEMA.labels]
    assert keys == [
        "rule_12d2_2_a1",
        "rule_12d2_2_a2",
        "rule_12d2_2_a3",
        "rule_12d2_2_a4",
        "rule_12d2_2_b",
        "rule_12d2_2_c",
    ]
    assert FORM_25_CHECKBOX_SCHEMA.family == "25"


def test_form_8a_schema_covers_instruction_boxes() -> None:
    keys = [label.key for label in FORM_8A_CHECKBOX_SCHEMA.labels]
    assert keys == [
        "section_12b_effective",
        "section_12g_effective",
        "regulation_a_concurrent",
    ]
