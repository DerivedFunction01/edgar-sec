"""Section taxonomy for free writing prospectuses: the terms block and
the tax section are the sections filed specimens evidence; the body is
otherwise deal prose keyed to the accompanying prospectus.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_FWP_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "SUMMARY TERMS",
        1,
        (
            "summary terms",
            "key terms",
        ),
        early=True,
    ),
    ItemDefinition(
        "TAX CONSIDERATIONS",
        1,
        (
            "tax considerations",
            "u.s. federal income tax considerations",
            "material u.s. federal income tax considerations",
        ),
        optional=True,
    ),
)

__all__ = ["FORM_FWP_ITEMS"]
