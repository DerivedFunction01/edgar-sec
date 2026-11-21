"""Form 12b-25 checkbox schema for subject reports and Part II relief."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import STATUTORY_BINARY_GROUP

FORM_12B25_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "subject_10k",
        (
            "form 10-k",
            "form 10 - k",
            "form 10k",
            "form 10-ksb",
            "form 10 - ksb",
            "form 10ksb",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "subject_20f",
        (
            "form 20-f",
            "form 20 - f",
            "form 20f",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "subject_11k",
        (
            "form 11-k",
            "form 11 - k",
            "form 11k",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "subject_10q",
        (
            "form 10-q",
            "form 10 - q",
            "form 10q",
            "form 10-qsb",
            "form 10 - qsb",
            "form 10qsb",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "subject_10d",
        (
            "form 10-d",
            "form 10 - d",
            "form 10d",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "subject_ncen",
        (
            "form n-cen",
            "form n - cen",
            "form ncen",
            "form n cen",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "subject_ncsr",
        (
            "form n-csr",
            "form n - csr",
            "form ncsr",
            "form n csr",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "transition_10k",
        (
            "transition report on form 10-k",
            "transition report on form 10 - k",
            "transition report on form 10k",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "transition_20f",
        (
            "transition report on form 20-f",
            "transition report on form 20 - f",
            "transition report on form 20f",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "transition_11k",
        (
            "transition report on form 11-k",
            "transition report on form 11 - k",
            "transition report on form 11k",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "transition_10q",
        (
            "transition report on form 10-q",
            "transition report on form 10 - q",
            "transition report on form 10q",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "part2_a",
        (
            "could not be eliminated without unreasonable effort or expense",
            "the reason described in reasonable detail in part iii of this form could not be eliminated without unreasonable effort or expense",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "part2_b",
        (
            "will be filed on or before the fifteenth calendar day following the prescribed due date",
            "will be filed on or before the fifth calendar day following the prescribed due date",
            "will be filed on or before the fifteenth calendar day",
            "will be filed on or before the fifth calendar day",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "part2_c",
        (
            "accountant's statement or other exhibit required by rule 12b-25(c)",
            "accountant's statement or other exhibit required by rule 12b-25 (c)",
            "accountant's statement or other exhibit required by rule 12b25(c)",
            "accountant's statement or other exhibit required by rule 12b25 (c)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

FORM_12B25_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="12B-25",
    groups=(STATUTORY_BINARY_GROUP,),
    labels=FORM_12B25_CHECKBOX_LABELS,
)

__all__ = [
    "FORM_12B25_CHECKBOX_LABELS",
    "FORM_12B25_CHECKBOX_SCHEMA",
]
