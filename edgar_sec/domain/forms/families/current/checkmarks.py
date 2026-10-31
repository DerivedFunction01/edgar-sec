"""Current report checkbox schemas and constraints."""

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

SIX_K_CHECKBOX_LABELS = (
    CheckboxLabelSpec(
        "annual_report_form_20f",
        ("form 20-f",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "annual_report_form_40f",
        ("form 40-f",),
        STATUTORY_BINARY_GROUP,
    ),
)

EIGHT_K_CHECKBOX_LABELS = (
    CheckboxLabelSpec(
        "written_communications_rule_425",
        ("written communications pursuant to rule 425",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "soliciting_material_rule_14a12",
        ("soliciting material pursuant to rule 14a-12",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "precommencement_communications_rule_14d2b",
        ("pre-commencement communications pursuant to rule 14d-2(b)",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "precommencement_communications_rule_13e4c",
        ("pre-commencement communications pursuant to rule 13e-4(c)",),
        STATUTORY_BINARY_GROUP,
    ),
)

SIX_K_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="6-K",
    groups=(FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
    labels=(*COMMON_CHECKBOX_LABELS, *SIX_K_CHECKBOX_LABELS),
)

EIGHT_K_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="8-K",
    groups=(FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
    labels=(*COMMON_CHECKBOX_LABELS, *EIGHT_K_CHECKBOX_LABELS),
)

__all__ = [
    "EIGHT_K_CHECKBOX_SCHEMA",
    "SIX_K_CHECKBOX_SCHEMA",
]
