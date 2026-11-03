"""Form F-1 / F-2 checkbox schemas: the shared statutory block plus
the emerging-growth-company lines in the common labels; F-2 adds its
Rule 434 checkmark line.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    COMMON_CHECKBOX_LABELS,
    STATUTORY_CHECKBOX_CONSTRAINTS,
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import (
    FILER_STATUS_GROUP,
    STATUTORY_BINARY_GROUP,
)

F1_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "rule_415",
        (
            "rule 415 under the securities act",
            "rule 415",
            "delayed or continuous basis",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_462b",
        (
            "rule 462(b)",
            "rule 462 (b)",
            "pursuant to rule 462(b)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_462c",
        (
            "rule 462(c)",
            "rule 462 (c)",
            "pursuant to rule 462(c)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

FORM_F1_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="F-1",
    groups=(FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
    labels=(*COMMON_CHECKBOX_LABELS, *F1_CHECKBOX_LABELS),
)

F2_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    *F1_CHECKBOX_LABELS,
    CheckboxLabelSpec(
        "rule_434",
        (
            "rule 434 under the securities act",
            "rule 434",
            "pursuant to rule 434",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

FORM_F2_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="F-2",
    groups=(FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
    labels=(*COMMON_CHECKBOX_LABELS, *F2_CHECKBOX_LABELS),
)

__all__ = [
    "F1_CHECKBOX_LABELS",
    "F2_CHECKBOX_LABELS",
    "FORM_F1_CHECKBOX_SCHEMA",
    "FORM_F2_CHECKBOX_SCHEMA",
]
