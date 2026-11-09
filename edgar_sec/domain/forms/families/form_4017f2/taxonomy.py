"""Section taxonomy for Form 40-17F2 custody certificates: the
blocks filed specimens evidence after the N-17f-2 certificate face.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_4017F2_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "INSTRUCTIONS",
        1,
        (
            "instructions",
            "this form must be given to your independent public accountant",
        ),
        optional=True,
    ),
    ItemDefinition(
        "MANAGEMENT STATEMENT",
        1,
        (
            "management statement regarding compliance with certain provisions of the investment company act of 1940",
            "report of management on compliance with certain provisions of the investment company act of 1940",
            "report of management on compliance with rule 17f-2 of the investment company act of 1940",
            "report of management on compliance",
        ),
        optional=True,
    ),
    ItemDefinition(
        "REPORT OF INDEPENDENT ACCOUNTANTS",
        1,
        (
            "report of independent registered public accounting firm",
            "report of independent accountants",
            "report of independent public accountant",
            "report of independent public accountants",
            "independent accountant's report",
            "independent accountant\u2019s report",
            "independent accountants report",
            "independent auditor's report",
            "independent auditor\u2019s report",
        ),
        optional=True,
    ),
)

__all__ = ["FORM_4017F2_ITEMS"]
