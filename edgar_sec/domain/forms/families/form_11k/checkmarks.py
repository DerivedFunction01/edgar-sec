"""Form 11-K checkbox schema for the (Mark One) report-type boxes."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import STATUTORY_BINARY_GROUP

FORM_11K_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "report_annual",
        (
            "annual report pursuant to section 15(d) of the securities exchange act of 1934",
            "annual report pursuant to section 15(d)",
            "annual report pursuant to section 15-(d) of the securities exchange act of 1934",
            "annual report pursuant to section 15-(d)",
        ),
        STATUTORY_BINARY_GROUP,
        period_role="companion",
    ),
    CheckboxLabelSpec(
        "report_transition",
        (
            "transition report pursuant to section 15(d) of the securities exchange act of 1934",
            "transition report pursuant to section 15(d)",
            "transition report pursuant to section 15-(d) of the securities exchange act of 1934",
            "transition report pursuant to section 15-(d)",
        ),
        STATUTORY_BINARY_GROUP,
        period_role="transition",
    ),
)

FORM_11K_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="11-K",
    groups=(STATUTORY_BINARY_GROUP,),
    labels=FORM_11K_CHECKBOX_LABELS,
)

__all__ = [
    "FORM_11K_CHECKBOX_LABELS",
    "FORM_11K_CHECKBOX_SCHEMA",
]
