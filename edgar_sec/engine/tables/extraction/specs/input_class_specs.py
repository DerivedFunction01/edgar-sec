"""Input-class evidence spec registry: the kind's parameter table.

The priced R18 seat vocabulary, keyed by family; the evaluator
lives in input_class_evidence, the seat act in competition."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_R18_SEAT_PRICING,
)


@dataclass(frozen=True, slots=True)
class InputClassEvidenceSpec:
    """Input-class seat parameters, declared as data.
    Priced leg: min_classes distinct tokens seat the family; a
    level3_input_classes group seats on the quantitative shape."""

    family: str
    input_classes: tuple[str, ...]
    min_classes: int
    level3_input_classes: tuple[str, ...] = ()
    provenance: str = PROV_R18_SEAT_PRICING


# Input-class seat specs, keyed by family: the one literal home
# of the kind's parameters, priced on the R18 pass population
# (the classes3 cell: P 1.000 / R .947, pooled).
INPUT_CLASS_EVIDENCE_SPECS: dict[str, InputClassEvidenceSpec] = {
    "valuation_model_assumptions": InputClassEvidenceSpec(
        family="valuation_model_assumptions",
        input_classes=(
            "volatility",
            "risk-free",
            "risk free",
            "dividend",
            "expected term",
            "expected life",
            "forfeiture",
            "exercise price",
            "stock price",
            "share price",
            "interest rate",
            "discount rate",
            "growth rate",
            "royalty",
            "weighted average cost",
            "correlation",
            "expected return",
            "illiquidity",
            "marketability",
            "expected dividend",
        ),
        min_classes=3,
        level3_input_classes=(
            "prepayment",
            "default rate",
            "severity",
            "pull-through",
            "discount margin",
            "probability of success",
            "market multiple",
            "contract pricing",
            "discount applied",
        ),
    ),
}
