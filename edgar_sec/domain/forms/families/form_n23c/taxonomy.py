"""Section taxonomies for the N-23C notice families: the blocks filed
specimens evidence, in filed order, per family.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_N23C1_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "PURCHASES STATEMENT",
        1,
        (
            "statement by registered closed-end investment company with respect to purchases of its own securities pursuant to rule n-23c-1 during the last calendar month",
            "statement by registered closed-end investment company with respect to purchases of its own securities pursuant to rule 23c-1 during the last calendar month",
        ),
        optional=True,
        early=True,
    ),
)

FORM_N23C2_ITEMS: tuple[ItemDefinition, ...] = (
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

FORM_N23C3_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "NOTIFICATION OF REPURCHASE OFFER",
        1,
        ("notification of repurchase offer",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "INVESTMENT COMPANY ACT FILE NUMBER",
        1,
        ("investment company act file number",),
        optional=True,
    ),
    ItemDefinition(
        "EXACT NAME OF INVESTMENT COMPANY",
        1,
        (
            "exact name of investment company as specified in registration statement",
            "exact name of investment company",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ADDRESS OF PRINCIPAL EXECUTIVE OFFICE",
        1,
        ("address of principal executive office",),
        optional=True,
    ),
    ItemDefinition(
        "OFFER TYPE ELECTION",
        1,
        ("check one of the following",),
        optional=True,
    ),
    ItemDefinition(
        "REPURCHASE OFFER DOCUMENT",
        1,
        ("repurchase offer document",),
        optional=True,
    ),
    ItemDefinition(
        "REPURCHASE OFFER TERMS",
        1,
        ("repurchase offer terms",),
        optional=True,
    ),
    ItemDefinition(
        "REPURCHASE REQUEST DEADLINE",
        1,
        ("repurchase request deadline",),
        optional=True,
    ),
    ItemDefinition(
        "REPURCHASE PRICING DATE",
        1,
        ("repurchase pricing date",),
        optional=True,
    ),
    ItemDefinition(
        "SUSPENSION OR POSTPONEMENT OF REPURCHASE OFFER",
        1,
        ("suspension or postponement of repurchase offer",),
        optional=True,
    ),
    ItemDefinition(
        "REPURCHASE REQUEST FORM",
        1,
        (
            "repurchase request form",
            "tender request form",
        ),
        optional=True,
    ),
    ItemDefinition(
        "LETTER OF TRANSMITTAL",
        1,
        ("letter of transmittal",),
        optional=True,
    ),
    ItemDefinition(
        "PAYMENT AND DELIVERY INSTRUCTIONS",
        1,
        ("payment and delivery instructions",),
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

__all__ = [
    "FORM_N23C1_ITEMS",
    "FORM_N23C2_ITEMS",
    "FORM_N23C3_ITEMS",
]
