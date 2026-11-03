"""Form F-6 checkbox schema for the Rule 466 effectiveness election."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    CheckboxConstraint,
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import STATUTORY_BINARY_GROUP

FORM_F6_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "rule_466_immediate",
        ("immediately upon filing",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_466_deferred",
        ("on (date) at (time)",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "separate_registration_statement",
        (
            "separate registration statement has been filed "
            "to register the deposited shares",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

FORM_F6_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="F-6",
    groups=(STATUTORY_BINARY_GROUP,),
    constraints=(
        CheckboxConstraint(
            name="rule_466_election_exclusion",
            relation="not_both",
            left="rule_466_immediate",
            right="rule_466_deferred",
            description="Rule 466 effectiveness is immediate or dated, not both.",
        ),
    ),
    labels=FORM_F6_CHECKBOX_LABELS,
)

__all__ = [
    "FORM_F6_CHECKBOX_LABELS",
    "FORM_F6_CHECKBOX_SCHEMA",
]
