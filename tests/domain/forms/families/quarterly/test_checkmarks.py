"""Tests for quarterly report checkbox schemas."""

from __future__ import annotations

from edgar_sec.domain.forms.families.quarterly.checkmarks import (
    QUARTERLY_CHECKBOX_SCHEMA,
)


def test_quarterly_checkbox_schema_properties() -> None:
    assert QUARTERLY_CHECKBOX_SCHEMA.family == "quarterly"
    assert "report_period" in QUARTERLY_CHECKBOX_SCHEMA.groups
    assert "filer_status" in QUARTERLY_CHECKBOX_SCHEMA.groups
    assert "statutory_binary" in QUARTERLY_CHECKBOX_SCHEMA.groups
    assert len(QUARTERLY_CHECKBOX_SCHEMA.constraints) > 0
