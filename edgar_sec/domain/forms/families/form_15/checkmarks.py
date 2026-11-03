"""Form 15 checkbox schema for rule provisions relied upon."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import STATUTORY_BINARY_GROUP

FORM_15_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "rule_12g4_a1",
        (
            "rule 12g-4(a)(1)",
            "rule 12g-4 (a)(1)",
            "rule 12g4(a)(1)",
            "rule 12g4 (a)(1)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_12g4_a2",
        (
            "rule 12g-4(a)(2)",
            "rule 12g-4 (a)(2)",
            "rule 12g4(a)(2)",
            "rule 12g4 (a)(2)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_12h3_b1_i",
        (
            "rule 12h-3(b)(1)(i)",
            "rule 12h-3 (b)(1)(i)",
            "rule 12h3(b)(1)(i)",
            "rule 12h3 (b)(1)(i)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_12h3_b1_ii",
        (
            "rule 12h-3(b)(1)(ii)",
            "rule 12h-3 (b)(1)(ii)",
            "rule 12h3(b)(1)(ii)",
            "rule 12h3 (b)(1)(ii)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_15d6",
        (
            "rule 15d-6",
            "rule 15d6",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

FORM_15_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="15",
    groups=(STATUTORY_BINARY_GROUP,),
    labels=FORM_15_CHECKBOX_LABELS,
)

__all__ = [
    "FORM_15_CHECKBOX_LABELS",
    "FORM_15_CHECKBOX_SCHEMA",
]
