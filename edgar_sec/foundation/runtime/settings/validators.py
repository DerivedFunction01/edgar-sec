"""Shared validators for typed setting specifications.

Every spec module needs the same numeric bounds checks. Declaring them once
here keeps the bound definitions identical: a spec that said ``> 0`` while its
sibling said ``>= 0`` would be a silent inconsistency no test would catch.
"""

from __future__ import annotations


def validate_positive_int(value: object) -> None:
    """Require an integer greater than zero."""
    if int(value) < 1:
        raise ValueError("must be >= 1")


def validate_non_negative_int(value: object) -> None:
    """Require an integer of zero or greater."""
    if int(value) < 0:
        raise ValueError("must be >= 0")


def validate_fraction(value: object) -> None:
    """Require a fraction above zero and at most one.

    The upper bound is inclusive. Narrowing it here would silently reject a value
    that currently resolves, which is a settings-breaking change and not a
    consolidation.
    """
    if not 0 < float(value) <= 1:
        raise ValueError("must be between 0 and 1")


__all__ = [
    "validate_fraction",
    "validate_non_negative_int",
    "validate_positive_int",
]
