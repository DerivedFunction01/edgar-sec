"""Form 40-F checkbox schema: election pair and furnished marks."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    COMMON_CHECKBOX_LABELS,
    STATUTORY_CHECKBOX_CONSTRAINTS,
    CheckboxConstraint,
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import (
    FILER_STATUS_GROUP,
    STATUTORY_BINARY_GROUP,
)

FORM_40F_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "section_12_registration",
        ("registration statement pursuant to section 12",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "section_13a_15d_annual_report",
        (
            "annual report pursuant to section 13(a) or 15(d)",
            "annual report pursuant to section 13 or 15(d)",
            "annual report pursuant to section 13(1) or 15(d)",
            "annual report pursuant to section 13(a)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "furnished_aif",
        ("annual information form",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "furnished_audited_financial_statements",
        ("audited annual financial statements",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_12g3_2b_furnishing",
        ("rule 12g3-2(b)",),
        STATUTORY_BINARY_GROUP,
    ),
)

FORM_40F_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="40-F",
    groups=(FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=(
        *STATUTORY_CHECKBOX_CONSTRAINTS,
        CheckboxConstraint(
            name="form_40f_election_exclusion",
            relation="not_both",
            left="section_12_registration",
            right="section_13a_15d_annual_report",
            description="The Section 12 / Section 13(a)-15(d) election is one-way.",
        ),
    ),
    labels=(*COMMON_CHECKBOX_LABELS, *FORM_40F_LABELS),
)

__all__ = [
    "FORM_40F_CHECKBOX_SCHEMA",
    "FORM_40F_LABELS",
]
