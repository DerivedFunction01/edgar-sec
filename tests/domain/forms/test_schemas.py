"""Unit tests for cover checkbox schemas and statutory constraints."""

from edgar_sec.domain.forms.schemas import (
    ANNUAL_CHECKBOX_SCHEMA,
    FILER_STATUS_GROUP,
    REPORT_PERIOD_GROUP,
    STATUTORY_BINARY_GROUP,
    STATUTORY_CHECKBOX_CONSTRAINTS,
    CheckboxConstraint,
)


def test_statutory_constraints_defined() -> None:
    assert len(STATUTORY_CHECKBOX_CONSTRAINTS) == 7

    names = {c.name for c in STATUTORY_CHECKBOX_CONSTRAINTS}
    assert "wksi_shell_exclusion" in names
    assert "wksi_12_month_compliance" in names
    assert "shell_404b_exemption" in names
    assert "recovery_requires_error_correction" in names


def test_annual_checkbox_schema() -> None:
    assert ANNUAL_CHECKBOX_SCHEMA.family == "annual"
    assert REPORT_PERIOD_GROUP in ANNUAL_CHECKBOX_SCHEMA.groups
    assert FILER_STATUS_GROUP in ANNUAL_CHECKBOX_SCHEMA.groups
    assert STATUTORY_BINARY_GROUP in ANNUAL_CHECKBOX_SCHEMA.groups
    assert ANNUAL_CHECKBOX_SCHEMA.constraints == STATUTORY_CHECKBOX_CONSTRAINTS


def test_checkbox_constraint_immutability() -> None:
    c = CheckboxConstraint(
        name="test_constraint",
        relation="not_both",
        left="stat_a",
        right="stat_b",
        penalty=250,
    )
    assert c.penalty == 250
    assert c.relation == "not_both"
