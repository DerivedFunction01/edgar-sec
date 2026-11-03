"""MJDS checkbox schemas for the Rule 467 effectiveness election.

F-7/F-8/F-80 are effective upon filing under Rule 467(a); F-9 and F-10
elect between Rule 467(a) and a future date under Rule 467(b).
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    CheckboxConstraint,
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import STATUTORY_BINARY_GROUP

_RULE_467A = CheckboxLabelSpec(
    "rule_467a_upon_filing",
    (
        "upon filing with the commission, pursuant to rule 467(a)",
        "upon filing with the commission pursuant to rule 467(a)",
        "shall become effective upon filing with the commission "
        "in accordance with rule 467(a)",
        "effective upon filing with the commission in accordance with rule 467(a)",
    ),
    STATUTORY_BINARY_GROUP,
)

_SHELF_BOX = CheckboxLabelSpec(
    "delayed_or_continuous_shelf",
    (
        "delayed or continuous basis pursuant to the home jurisdiction's "
        "shelf prospectus offering procedures",
        "delayed or continuous basis pursuant to the home jurisdiction’s "
        "shelf prospectus offering procedures",
    ),
    STATUTORY_BINARY_GROUP,
)

MJDS_AUTOMATIC_LABELS: tuple[CheckboxLabelSpec, ...] = (_RULE_467A, _SHELF_BOX)

MJDS_ELECTION_LABELS: tuple[CheckboxLabelSpec, ...] = (
    _RULE_467A,
    CheckboxLabelSpec(
        "effectiveness_future_date",
        ("at some future date",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_467b_designated_date",
        (
            "pursuant to rule 467(b) on",
            "not sooner than seven calendar days after filing",
            "not sooner than 7 calendar days after filing",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_467b_receipt_clearance",
        ("has issued a receipt or notification of clearance",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_467b_notification",
        (
            "as soon as practicable after notification of the commission "
            "by the registrant",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    _SHELF_BOX,
)

MJDS_ELECTION_CONSTRAINTS: tuple[CheckboxConstraint, ...] = (
    CheckboxConstraint(
        name="effectiveness_election_exclusion",
        relation="not_both",
        left="rule_467a_upon_filing",
        right="effectiveness_future_date",
        description="Rule 467(a) filing effectiveness excludes a future date.",
    ),
)


def _schema(
    family: str,
    labels: tuple[CheckboxLabelSpec, ...],
    constraints: tuple[CheckboxConstraint, ...] = (),
) -> CoverCheckboxSchema:
    return CoverCheckboxSchema(
        family=family,
        groups=(STATUTORY_BINARY_GROUP,),
        constraints=constraints,
        labels=labels,
    )


FORM_F7_CHECKBOX_SCHEMA = _schema("F-7", MJDS_AUTOMATIC_LABELS)
FORM_F8_CHECKBOX_SCHEMA = _schema("F-8", MJDS_AUTOMATIC_LABELS)
FORM_F80_CHECKBOX_SCHEMA = _schema("F-80", MJDS_AUTOMATIC_LABELS)
FORM_F9_CHECKBOX_SCHEMA = _schema(
    "F-9", MJDS_ELECTION_LABELS, MJDS_ELECTION_CONSTRAINTS
)
FORM_F10_CHECKBOX_SCHEMA = _schema(
    "F-10", MJDS_ELECTION_LABELS, MJDS_ELECTION_CONSTRAINTS
)

__all__ = [
    "FORM_F10_CHECKBOX_SCHEMA",
    "FORM_F7_CHECKBOX_SCHEMA",
    "FORM_F80_CHECKBOX_SCHEMA",
    "FORM_F8_CHECKBOX_SCHEMA",
    "FORM_F9_CHECKBOX_SCHEMA",
    "MJDS_AUTOMATIC_LABELS",
    "MJDS_ELECTION_CONSTRAINTS",
    "MJDS_ELECTION_LABELS",
]
