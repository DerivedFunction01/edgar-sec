"""Tests for annual report checkbox schemas."""

from __future__ import annotations

from edgar_sec.domain.forms.families.annual.checkmarks import ANNUAL_CHECKBOX_SCHEMA


def test_annual_checkbox_schema_properties() -> None:
    assert ANNUAL_CHECKBOX_SCHEMA.family == "annual"
    assert "report_period" in ANNUAL_CHECKBOX_SCHEMA.groups
    assert "filer_status" in ANNUAL_CHECKBOX_SCHEMA.groups
    assert "statutory_binary" in ANNUAL_CHECKBOX_SCHEMA.groups
    assert len(ANNUAL_CHECKBOX_SCHEMA.constraints) > 0
