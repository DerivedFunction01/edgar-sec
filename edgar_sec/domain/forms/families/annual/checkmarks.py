"""Annual report checkbox schemas and constraints."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    FILER_STATUS_GROUP,
    REPORT_PERIOD_GROUP,
    STATUTORY_BINARY_GROUP,
    STATUTORY_CHECKBOX_CONSTRAINTS,
    CoverCheckboxSchema,
)

ANNUAL_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="annual",
    groups=(REPORT_PERIOD_GROUP, FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
)

__all__ = [
    "ANNUAL_CHECKBOX_SCHEMA",
]
