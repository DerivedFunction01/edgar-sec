"""Percentage-form specs: one per family declaring the kind."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PercentageFormSpec:
    """One family's percentage-form test, declared as data."""

    family: str
    anchor_tokens: tuple[str, ...]
    total_tokens: tuple[str, ...]
    min_adjustments: int = 1
    closure_tolerance: float = 0.3
    min_columns: int = 1


# Percentage-form specs (class (iii)): one per family
# declaring TEST_PERCENTAGE_FORM, pinned from the measured
# directed sets and the adjudicated specimens in each note.
PERCENTAGE_SPECS: tuple[PercentageFormSpec, ...] = (
    PercentageFormSpec(
        "tax_reconciliation",
        anchor_tokens=(
            "statutory rate",
            "statutory tax",
            "at statutory",
            "statutory federal",
            "federal statutory",
        ),
        total_tokens=(
            "effective tax",
            "effective income tax",
            "effective rate",
        ),
        min_adjustments=1,
        closure_tolerance=0.3,
    ),
)

PERCENTAGE_SPECS_BY_FAMILY = {spec.family: spec for spec in PERCENTAGE_SPECS}
