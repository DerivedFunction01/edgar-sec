"""Section taxonomy for Form 24F-2 Rule 24f-2 fee notices: the
numbered captions filed specimens evidence, in filed order.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_24F2_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "NAME AND ADDRESS OF ISSUER",
        1,
        ("name and address of issuer",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "SERIES OR CLASS",
        1,
        (
            "name of each series or class of securities for which this form is filed",
            "name of each series or class of funds for which this notice is filed",
        ),
        optional=True,
    ),
    ItemDefinition(
        "FILE NUMBERS",
        1,
        ("investment company act file number",),
        optional=True,
    ),
    ItemDefinition(
        "FISCAL YEAR END",
        1,
        (
            "last day of fiscal year for which this notice is filed",
            "last day of fiscal year for which this form is filed",
        ),
        optional=True,
    ),
    ItemDefinition(
        "SECURITIES REGISTERED AND SOLD",
        1,
        (
            "number and amount of securities of the same class or series",
            "number and aggregate sale price of securities sold during the fiscal year",
        ),
        optional=True,
    ),
    ItemDefinition(
        "CALCULATION OF REGISTRATION FEE",
        1,
        ("calculation of registration fee",),
        optional=True,
    ),
    ItemDefinition(
        "PREPAID SHARES",
        1,
        ("prepaid shares",),
        optional=True,
    ),
    ItemDefinition(
        "INTEREST DUE",
        1,
        ("interest due",),
        optional=True,
    ),
    ItemDefinition(
        "TOTAL AMOUNT DUE",
        1,
        ("total of the amount of the registration fee due plus any interest due",),
        optional=True,
    ),
    ItemDefinition(
        "PAYMENT DATE",
        1,
        ("date the registration fee and any interest payment was sent",),
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

__all__ = ["FORM_24F2_ITEMS"]
