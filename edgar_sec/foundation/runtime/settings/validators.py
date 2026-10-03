"""Shared validators for typed setting specifications.

Bounds are declared once here so sibling specs cannot disagree.
"""

from __future__ import annotations


def validate_positive_int(value: object) -> None:
    if int(value) < 1:
        raise ValueError("must be >= 1")


def validate_non_negative_int(value: object) -> None:
    if int(value) < 0:
        raise ValueError("must be >= 0")


def validate_fraction(value: object) -> None:
    """Require a fraction above zero and at most one.

    The upper bound is inclusive: narrowing it would reject a value that currently
    resolves, which is a settings-breaking change rather than a consolidation.
    """
    if not 0 < float(value) <= 1:
        raise ValueError("must be between 0 and 1")


__all__ = [
    "validate_fraction",
    "validate_non_negative_int",
    "validate_positive_int",
]
