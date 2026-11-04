"""Checkbox schema for the ABS reports faces.

The 10-D face's reports-filed mark rides the common label set; the
ABS-15G face adds its Rule 15Ga-1 / 15Ga-2 obligation pair and the
three no-activity marks of Rule 15Ga-1(c).
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    COMMON_CHECKBOX_LABELS,
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import STATUTORY_BINARY_GROUP

ABS_15G_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "rule_15ga_1",
        (
            "rule 15ga-1 under the exchange act",
            "17 cfr 240.15ga-1",
            "240.15ga-1",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_15ga_2",
        (
            "rule 15ga-2 under the exchange act",
            "17 cfr 240.15ga-2",
            "240.15ga-2",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "no_activity_initial",
        (
            "no activity to report for the initial period",
            "15ga-1(c)(1)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "no_activity_quarterly",
        (
            "no activity to report for the quarterly period",
            "15ga-1(c)(2)(i)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "no_activity_annual",
        (
            "no activity to report for the annual period",
            "15ga-1(c)(2)(ii)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

ABS_REPORTS_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="ABS",
    groups=(STATUTORY_BINARY_GROUP,),
    labels=(*COMMON_CHECKBOX_LABELS, *ABS_15G_CHECKBOX_LABELS),
)

__all__ = [
    "ABS_15G_CHECKBOX_LABELS",
    "ABS_REPORTS_CHECKBOX_SCHEMA",
]
