"""Section taxonomy for Form 40-17G fidelity-bond filings: the bond
instrument blocks filed specimens evidence, in filed order.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_4017G_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "DECLARATIONS",
        1,
        ("declarations",),
        optional=True,
    ),
    ItemDefinition(
        "INSURING AGREEMENTS",
        1,
        ("insuring agreements",),
        optional=True,
    ),
    ItemDefinition(
        "GENERAL AGREEMENTS",
        1,
        ("general agreements",),
        optional=True,
    ),
    ItemDefinition(
        "CONDITIONS AND LIMITATIONS",
        1,
        ("conditions and limitations",),
        optional=True,
    ),
    ItemDefinition(
        "SIGNATURES",
        1,
        (
            "signatures",
            "signature",
        ),
        optional=True,
    ),
)

__all__ = ["FORM_4017G_ITEMS"]
