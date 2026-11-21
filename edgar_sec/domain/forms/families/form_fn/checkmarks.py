"""Form F-N checkbox schema: the original/amendment filing marks only."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    CheckboxConstraint,
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import STATUTORY_BINARY_GROUP

FORM_FN_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "original_filing",
        ("an original filing for the filer",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "amended_filing",
        ("an amended filing for the filer",),
        STATUTORY_BINARY_GROUP,
    ),
)

FORM_FN_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="F-N",
    groups=(STATUTORY_BINARY_GROUP,),
    constraints=(
        CheckboxConstraint(
            name="filing_kind_exclusion",
            relation="not_both",
            left="original_filing",
            right="amended_filing",
            description="A filing is original or amended, not both.",
        ),
    ),
    labels=FORM_FN_CHECKBOX_LABELS,
)

__all__ = [
    "FORM_FN_CHECKBOX_LABELS",
    "FORM_FN_CHECKBOX_SCHEMA",
]
