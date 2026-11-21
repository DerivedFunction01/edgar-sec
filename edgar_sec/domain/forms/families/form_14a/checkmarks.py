"""Schedule 14A checkbox schema for the cover classification and fee boxes."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import STATUTORY_BINARY_GROUP

FORM_14A_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "filed_by_registrant",
        ("filed by the registrant",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "filed_by_other_party",
        (
            "filed by a party other than the registrant",
            "filed by a party other than registrant",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "classification_preliminary",
        ("preliminary proxy statement", "preliminary information statement"),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "classification_confidential",
        (
            "confidential, for use of the commission only",
            "confidential for use of the commission only",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "classification_definitive",
        ("definitive proxy statement", "definitive information statement"),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "classification_definitive_additional",
        ("definitive additional materials",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "classification_soliciting_material",
        (
            "soliciting material under §240.14a-12",
            "soliciting material pursuant to §240.14a-12",
            "soliciting material under rule 14a-12",
            "soliciting material pursuant to rule 14a-12",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "fee_not_required",
        ("no fee required",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "fee_paid_previously",
        ("fee paid previously with preliminary materials",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "fee_computed_on_table",
        (
            "fee computed on table in exhibit required by item 25(b)",
            "fee computed on table below",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

FORM_14A_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="14A",
    groups=(STATUTORY_BINARY_GROUP,),
    labels=FORM_14A_CHECKBOX_LABELS,
)

__all__ = [
    "FORM_14A_CHECKBOX_LABELS",
    "FORM_14A_CHECKBOX_SCHEMA",
]
