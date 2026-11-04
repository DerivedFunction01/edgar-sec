"""Checkbox schemas for the Section 12 cluster faces."""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import STATUTORY_BINARY_GROUP

FORM_25_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "rule_12d2_2_a1",
        ("17 cfr 240.12d2-2(a)(1)", "240.12d2-2(a)(1)", "12d2-2(a)(1)"),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_12d2_2_a2",
        ("17 cfr 240.12d2-2(a)(2)", "240.12d2-2(a)(2)", "12d2-2(a)(2)"),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_12d2_2_a3",
        ("17 cfr 240.12d2-2(a)(3)", "240.12d2-2(a)(3)", "12d2-2(a)(3)"),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_12d2_2_a4",
        ("17 cfr 240.12d2-2(a)(4)", "240.12d2-2(a)(4)", "12d2-2(a)(4)"),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_12d2_2_b",
        ("17 cfr 240.12d2-2(b)", "240.12d2-2(b)", "12d2-2(b)"),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "rule_12d2_2_c",
        ("17 cfr 240.12d2-2(c)", "240.12d2-2(c)", "12d2-2(c)"),
        STATUTORY_BINARY_GROUP,
    ),
)

FORM_25_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="25",
    groups=(STATUTORY_BINARY_GROUP,),
    labels=FORM_25_CHECKBOX_LABELS,
)

FORM_8A_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "section_12b_effective",
        (
            "registration of a class of securities pursuant to section 12(b)",
            "relates to the registration of a class of securities pursuant to section 12(b)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "section_12g_effective",
        (
            "registration of a class of securities pursuant to section 12(g)",
            "relates to the registration of a class of securities pursuant to section 12(g)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "regulation_a_concurrent",
        (
            "registration of a class of securities concurrently with a regulation a offering",
            "relates to the registration of a class of securities concurrently with a regulation a offering",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

FORM_8A_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="8-A",
    groups=(STATUTORY_BINARY_GROUP,),
    labels=FORM_8A_CHECKBOX_LABELS,
)

__all__ = [
    "FORM_25_CHECKBOX_LABELS",
    "FORM_25_CHECKBOX_SCHEMA",
    "FORM_8A_CHECKBOX_LABELS",
    "FORM_8A_CHECKBOX_SCHEMA",
]
