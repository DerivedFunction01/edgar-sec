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

S3_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    *S1_CHECKBOX_LABELS[:3],  # rule_415, rule_462b, rule_462c
    CheckboxLabelSpec(
        "rule_462e",
        (
            "rule 462(e)",
            "rule 462 (e)",
            "pursuant to rule 462(e)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_413b",
        (
            "rule 413(b)",
            "rule 413 (b)",
            "pursuant to rule 413(b)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

S3_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="S-3",
    groups=(FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
    labels=(*COMMON_CHECKBOX_LABELS, *S3_CHECKBOX_LABELS),
)

S4_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "instruction_g",
        (
            "general instruction g",
            "instruction g",
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
        "rule_462d",
        (
            "rule 462(d)",
            "rule 462 (d)",
            "pursuant to rule 462(d)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_13e4i",
        (
            "rule 13e-4(i)",
            "rule 13e-4 (i)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_14d1d",
        (
            "rule 14d-1(d)",
            "rule 14d-1 (d)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

S4_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="S-4",
    groups=(FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
    labels=(*COMMON_CHECKBOX_LABELS, *S4_CHECKBOX_LABELS),
)

S8_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="S-8",
    groups=(FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
    labels=COMMON_CHECKBOX_LABELS,
)

__all__ = [
    "S1_CHECKBOX_LABELS",
    "S1_CHECKBOX_SCHEMA",
    "S3_CHECKBOX_LABELS",
    "S3_CHECKBOX_SCHEMA",
    "S4_CHECKBOX_LABELS",
    "S4_CHECKBOX_SCHEMA",
    "S8_CHECKBOX_SCHEMA",
]
