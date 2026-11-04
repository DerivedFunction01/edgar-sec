"""Tender checkbox schema for the Schedule TO designation blocks and the
the earlier Schedule 13E-3 connection block; every box is independent.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.schemas import (
    CheckboxLabelSpec,
    CoverCheckboxSchema,
)
from edgar_sec.domain.forms.common.vocabulary import STATUTORY_BINARY_GROUP

TENDER_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    CheckboxLabelSpec(
        "fee_offset_rule_0_11",
        (
            "check the box if any part of the fee is offset as provided by rule 0-11(a)(2)",
            "any part of the fee is offset as provided by rule 0-11(a)(2)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "preliminary_communications",
        (
            "check the box if the filing relates solely to preliminary communications made before the commencement of a tender offer",
            "relates solely to preliminary communications made before the commencement of a tender offer",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "third_party_tender_offer",
        (
            "third-party tender offer subject to rule 14d-1",
            "third party tender offer subject to rule 14d-1",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "issuer_tender_offer",
        ("issuer tender offer subject to rule 13e-4",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "going_private_transaction",
        (
            "going private transaction subject to rule 13e-3",
            "going-private transaction subject to rule 13e-3",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "schedule_13d_amendment",
        ("amendment to schedule 13d under rule 13d-2",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "final_amendment",
        ("final amendment reporting the results of the tender offer",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "cross_border_issuer_tender_offer",
        (
            "rule 13e-4(i) (cross-border issuer tender offer)",
            "rule 13e-4(i)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "cross_border_third_party_tender_offer",
        (
            "rule 14d-1(d) (cross-border third-party tender offer)",
            "rule 14d-1(d)",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "connection_solicitation_materials",
        (
            "the filing of solicitation materials or an information statement subject to regulation 14a, regulation 14c",
            "filing of solicitation materials or an information statement",
        ),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "connection_registration_statement",
        ("the filing of a registration statement under the securities act of 1933",),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        "preliminary_solicitation_copies",
        (
            "check the following box if the soliciting materials or information statement referred to in checking box (a) are preliminary copies",
            "are preliminary copies",
        ),
        STATUTORY_BINARY_GROUP,
    ),
)

TENDER_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="SC TO",
    groups=(STATUTORY_BINARY_GROUP,),
    labels=TENDER_CHECKBOX_LABELS,
)

__all__ = [
    "TENDER_CHECKBOX_LABELS",
    "TENDER_CHECKBOX_SCHEMA",
]
