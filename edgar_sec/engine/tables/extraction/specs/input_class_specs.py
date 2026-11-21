"""Input-class evidence spec registry: the kind's parameter table.

The priced R18 seat vocabulary, keyed by family; the evaluator
lives in input_class_evidence, the seat act in competition."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROV_R18_SEAT_PRICING,
)


@dataclass(frozen=True, slots=True)
class InputClassEvidenceSpec:
    """Input-class seat parameters, declared as data.
    The priced leg: canonical input-class tokens over the grid
    text; at least min_classes distinct classes seat the family."""

    family: str
    input_classes: tuple[str, ...]
    min_classes: int
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
    ),
}
