"""Annual report checkbox schemas and constraints."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    COMMON_CHECKBOX_LABELS,
    STATUTORY_CHECKBOX_CONSTRAINTS,
    TRANSITION_REPORT_LABEL,
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import (
    FILER_STATUS_GROUP,
    REPORT_PERIOD_GROUP,
    STATUTORY_BINARY_GROUP,
)

ANNUAL_REPORT_LABEL = CheckboxLabelSpec(
    "annual",
    (
        "annual report",
        "annual reports",
        "annual report pursuant",
        "annual reports pursuant",
    ),
    REPORT_PERIOD_GROUP,
    "companion",
)

ANNUAL_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="annual",
    groups=(REPORT_PERIOD_GROUP, FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
    labels=(*COMMON_CHECKBOX_LABELS, ANNUAL_REPORT_LABEL, TRANSITION_REPORT_LABEL),
)

__all__ = [
    "ANNUAL_CHECKBOX_SCHEMA",
]
