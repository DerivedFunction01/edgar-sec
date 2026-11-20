"""Restructuring separator evidence (TEST_RESTRUCTURING_SEPARATOR).
Evaluates the priced composition over one table's grid: a restructuring
claim is refused on a bookend-free three-year span, or on unchanged
walked balances with no nonzero movement (the rollforward grid reads)."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.restructuring_separator_specs import (
    RESTRUCTURING_SEPARATOR_SPECS,
    RestructuringSeparatorSpec,
)
from edgar_sec.engine.tables.extraction.rollforward_grid_evidence import (
    RollforwardGridText,
    grid_features,
)

__all__ = [
    "RestructuringSeparatorVerdict",
    "RollforwardGridText",
    "evaluate_form_test_restructuring_separator",
    "evaluate_restructuring_separator",
    "fired_separator_outcome",
]


@dataclass(frozen=True)
class RestructuringSeparatorVerdict:
    """The separator verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def evaluate_restructuring_separator(
    text: RollforwardGridText, spec: RestructuringSeparatorSpec
) -> RestructuringSeparatorVerdict:
    """Evaluate one grid against the family's priced legs."""
    features = grid_features(text)
    if features.rows == 0:
        return RestructuringSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    fired: list[str] = []
    for leg in spec.legs:
        if leg.scope != "claim-local":
            continue
        if (
            leg.kind == "no_bookend_span"
            and not features.bookend_f2
            and features.span >= leg.limit
        ):
            fired.append(leg.leg_id)
        elif (
            leg.kind == "zero_activity"
            and features.movement_nonzero <= 0
            and features.balances_unchanged
        ):
            fired.append(leg.leg_id)
    if fired:
        detail = "separator fired: " + ", ".join(fired)
        return RestructuringSeparatorVerdict(True, True, tuple(fired), detail)
    return RestructuringSeparatorVerdict(False, True, (), "separator clear")


# ---------------- production wiring (stage adapter + gate) ----------------


def evaluate_form_test_restructuring_separator(table, spec):
    """Stage adapter: evaluate the declared separator over a table."""
    gate_spec = RESTRUCTURING_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return RestructuringSeparatorVerdict(
            False, False, (), "no separator spec for family"
        )
    text = RollforwardGridText.from_rows(table.context.rows)
    return evaluate_restructuring_separator(text, gate_spec)
