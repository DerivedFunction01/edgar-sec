"""Checkbox schema for the Form SD rule-election pair."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import STATUTORY_BINARY_GROUP

SD_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "rule_13p_1",
        (
            "rule 13p-1 under the securities exchange act (17 cfr 240.13p-1) for the reporting period from january 1 to december 31",
            "rule 13p-1 under the securities exchange act (17 cfr 240.13p-1)",
            "rule 13p-1 under the securities exchange act",
            "17 cfr 240.13p-1",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_13q_1",
        (
            "rule 13q-1 under the securities exchange act (17 cfr 240.13q-1) for the fiscal year ended",
            "rule 13q-1 under the securities exchange act (17 cfr 240.13q-1)",
            "rule 13q-1 under the securities exchange act",
            "17 cfr 240.13q-1",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

SD_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="SD",
    groups=(STATUTORY_BINARY_GROUP,),
    labels=SD_CHECKBOX_LABELS,
)

__all__ = ["SD_CHECKBOX_LABELS", "SD_CHECKBOX_SCHEMA"]
