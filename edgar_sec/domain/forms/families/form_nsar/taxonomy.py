"""Answer-file taxonomy for Form NSAR: the keyed item blocks the filed
answer files evidence (registrant, adviser, underwriter, custodian,
accountants), keyed by their three-digit item numbers.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_NSAR_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "REGISTRANT IDENTITY",
        1,
        ("001 a",),
        early=True,
    ),
    ItemDefinition(
        "INVESTMENT ADVISER",
        8,
        ("008 a",),
        optional=True,
    ),
    ItemDefinition(
        "PRINCIPAL UNDERWRITER",
        10,
        ("010 a",),
        optional=True,
    ),
    ItemDefinition(
        "CUSTODIAN",
        12,
        ("012 a",),
        optional=True,
    ),
    ItemDefinition(
        "INDEPENDENT ACCOUNTANTS",
        13,
        ("013 a",),
        optional=True,
    ),
)

__all__ = ["FORM_NSAR_ITEMS"]
