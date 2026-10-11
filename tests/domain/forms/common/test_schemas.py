"""Unit tests for cover checkbox schemas and statutory constraints."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    COMMON_CHECKBOX_LABELS,
    STATUTORY_CHECKBOX_CONSTRAINTS,
    CheckboxConstraint,
)
from edgar_sec.domain.forms.common.vocabulary import (
    FILER_STATUS_GROUP,
    FILER_TYPE_LABELS,
)


def test_statutory_constraints_defined() -> None:
    assert len(STATUTORY_CHECKBOX_CONSTRAINTS) == 7

    names = {c.name for c in STATUTORY_CHECKBOX_CONSTRAINTS}
    assert "wksi_shell_exclusion" in names
    assert "wksi_12_month_compliance" in names
    assert "shell_404b_exemption" in names
    assert "recovery_requires_error_correction" in names


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


def test_filer_checkbox_schema_uses_the_canonical_label_mapping() -> None:
    labels = tuple(
        (label.key, label.phrases)
        for label in COMMON_CHECKBOX_LABELS
        if label.group == FILER_STATUS_GROUP
    )

    assert labels == tuple(FILER_TYPE_LABELS.items())
