from __future__ import annotations

from edgar_sec.domain.forms.families.registration.checkmarks import (
    S1_CHECKBOX_SCHEMA,
    S3_CHECKBOX_SCHEMA,
    S4_CHECKBOX_SCHEMA,
    S8_CHECKBOX_SCHEMA,
)


def test_s1_checkbox_schema_properties() -> None:
    assert S1_CHECKBOX_SCHEMA.family == "S-1"
    assert "filer_status" in S1_CHECKBOX_SCHEMA.groups
    assert "statutory_binary" in S1_CHECKBOX_SCHEMA.groups
    assert len(S1_CHECKBOX_SCHEMA.constraints) > 0


def test_s3_checkbox_schema_properties() -> None:
    assert S3_CHECKBOX_SCHEMA.family == "S-3"
    assert "filer_status" in S3_CHECKBOX_SCHEMA.groups
    assert "statutory_binary" in S3_CHECKBOX_SCHEMA.groups
    labels = {lbl.key for lbl in S3_CHECKBOX_SCHEMA.labels}
    assert "rule_462e" in labels
    assert "rule_413b" in labels


def test_s4_checkbox_schema_properties() -> None:
    assert S4_CHECKBOX_SCHEMA.family == "S-4"
    assert "filer_status" in S4_CHECKBOX_SCHEMA.groups
    assert "statutory_binary" in S4_CHECKBOX_SCHEMA.groups
    labels = {lbl.key for lbl in S4_CHECKBOX_SCHEMA.labels}
    assert "instruction_g" in labels
    assert "rule_13e4i" in labels


def test_s8_checkbox_schema_properties() -> None:
    assert S8_CHECKBOX_SCHEMA.family == "S-8"
    assert "filer_status" in S8_CHECKBOX_SCHEMA.groups
    assert "statutory_binary" in S8_CHECKBOX_SCHEMA.groups
