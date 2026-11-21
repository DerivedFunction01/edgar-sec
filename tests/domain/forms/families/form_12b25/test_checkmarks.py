from __future__ import annotations

from edgar_sec.domain.forms.families.form_12b25.checkmarks import (
    FORM_12B25_CHECKBOX_SCHEMA,
)


def test_form_12b25_checkbox_schema_properties() -> None:
    assert FORM_12B25_CHECKBOX_SCHEMA.family == "12B-25"
    assert FORM_12B25_CHECKBOX_SCHEMA.groups == ("statutory_binary",)
    assert FORM_12B25_CHECKBOX_SCHEMA.constraints == ()


def test_form_12b25_checkbox_schema_labels() -> None:
    keys = [label.key for label in FORM_12B25_CHECKBOX_SCHEMA.labels]
    assert keys == [
        "subject_10k",
        "subject_20f",
        "subject_11k",
        "subject_10q",
        "subject_10d",
        "subject_ncen",
        "subject_ncsr",
        "transition_10k",
        "transition_20f",
        "transition_11k",
        "transition_10q",
        "part2_a",
        "part2_b",
        "part2_c",
    ]
    for label in FORM_12B25_CHECKBOX_SCHEMA.labels:
        assert label.group == "statutory_binary"
        assert label.phrases


def test_form_12b25_checkbox_schema_phrases() -> None:
    labels = {label.key: label for label in FORM_12B25_CHECKBOX_SCHEMA.labels}
    assert labels["subject_10k"].phrases[0] == "form 10-k"
    assert labels["subject_ncsr"].phrases[0] == "form n-csr"
    assert labels["transition_10q"].phrases[0] == "transition report on form 10-q"
    assert "fifteenth calendar day" in " ".join(labels["part2_b"].phrases)
    assert "fifth calendar day" in " ".join(labels["part2_b"].phrases)
    assert "rule 12b-25(c)" in " ".join(labels["part2_c"].phrases)
