"""Registration statement checkbox schemas and constraints."""

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

S1_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
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
    CheckboxLabelSpec(
        "rule_462d",
        (
            "rule 462(d)",
            "rule 462 (d)",
            "pursuant to rule 462(d)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

S1_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="S-1",
    groups=(FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
    labels=(*COMMON_CHECKBOX_LABELS, *S1_CHECKBOX_LABELS),
)

__all__ = [
    "S1_CHECKBOX_LABELS",
    "S1_CHECKBOX_SCHEMA",
]
