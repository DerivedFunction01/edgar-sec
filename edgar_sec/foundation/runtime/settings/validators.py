"""Shared validators and argparse type callables for typed setting specs.

Bounds are declared once here so sibling specs cannot disagree.
"""

from __future__ import annotations


def positive_int_type(value: str) -> int:
    """Convert a string to a positive int (>= 1) for argparse ``type=``."""
    result = int(value)
    if result < 1:
        raise ValueError("must be >= 1")
    return result


def non_negative_int_type(value: str) -> int:
    """Convert a string to a non-negative int (>= 0) for argparse ``type=``."""
    result = int(value)
    if result < 0:
        raise ValueError("must be >= 0")
    return result


def validate_positive_int(value: object) -> None:
    positive_int_type(str(value))


def validate_non_negative_int(value: object) -> None:
    non_negative_int_type(str(value))


def validate_fraction(value: object) -> None:
    """Require a fraction above zero and at most one.

    The upper bound is inclusive: narrowing it would reject a value that currently
    resolves, which is a settings-breaking change rather than a consolidation.
    """
    if not 0 < float(value) <= 1:
        raise ValueError("must be between 0 and 1")


__all__ = [
    "positive_int_type",
    "non_negative_int_type",
    "validate_fraction",
    "validate_non_negative_int",
    "validate_positive_int",
]
