"""Independent gold ground-truth oracle and hidden-arc evaluation metrics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Mapping

from edgar_sec.engine.xbrl.models import CalculationArc

STANDARD_PREFIXES = frozenset({"us-gaap", "dei", "srt", "country", "currency", "xbrli"})


@dataclass(frozen=True, slots=True)
class ExtensionGroundTruth:
    """True published calculation placement for an extension element."""

    concept_qname: str
    parent_node: str
    weight: float
    role_uri: str | None = None


@dataclass(frozen=True, slots=True)
class PlacementPrediction:
    """Predicted placement decision produced by a solver."""

    concept_qname: str
    predicted_parent: str | None
    predicted_weight: float | None
    is_abstained: bool = False


@dataclass(frozen=True, slots=True)
class PlacementMetrics:
    """Section 9 evaluation metrics for extension concept placement."""

    total_evaluations: int
    placement_accuracy: float
    precision: float
    coverage: float
    abstention_rate: float
    exact_matches: int
    abstained_count: int


def is_extension_concept(concept_qname: str) -> bool:
    """Return True if concept QName belongs to a registrant custom taxonomy."""
    prefix = concept_qname.split(":")[0] if ":" in concept_qname else concept_qname
    return prefix.lower() not in STANDARD_PREFIXES


def extract_extension_ground_truth(
    calculation_arcs: Sequence[CalculationArc],
) -> tuple[tuple[CalculationArc, ...], tuple[ExtensionGroundTruth, ...]]:
    """Partition calculation arcs into core baseline and withheld extension gold."""
    core_arcs: list[CalculationArc] = []
    gold: list[ExtensionGroundTruth] = []

    for arc in calculation_arcs:
        if is_extension_concept(arc.child_qname):
            gold.append(
                ExtensionGroundTruth(
                    concept_qname=arc.child_qname,
                    parent_node=arc.parent_qname,
                    weight=arc.weight,
                    role_uri=arc.role_uri,
                )
            )
        else:
            core_arcs.append(arc)

    return tuple(core_arcs), tuple(gold)


def evaluate_placement_accuracy(
    ground_truth: Sequence[ExtensionGroundTruth],
    predictions: Sequence[PlacementPrediction] | Mapping[str, PlacementPrediction],
) -> PlacementMetrics:
    """Calculate Rule M4 placement accuracy, precision, and abstention rates."""
    pred_map = (
        predictions
        if isinstance(predictions, Mapping)
        else {p.concept_qname: p for p in predictions}
    )

    total = len(ground_truth)
    if total == 0:
        return PlacementMetrics(
            total_evaluations=0,
            placement_accuracy=0.0,
            precision=0.0,
            coverage=0.0,
            abstention_rate=0.0,
            exact_matches=0,
            abstained_count=0,
        )

    exact_matches = 0
    placed_count = 0
    abstained_count = 0

    for gt in ground_truth:
        pred = pred_map.get(gt.concept_qname)
        if pred is None or pred.is_abstained:
            abstained_count += 1
            continue

        placed_count += 1
        parent_match = pred.predicted_parent == gt.parent_node
        weight_match = (
            abs((pred.predicted_weight or 0.0) - gt.weight) <= 0.01
            if pred.predicted_weight is not None
            else False
        )
        if parent_match and weight_match:
            exact_matches += 1

    placement_accuracy = round(100.0 * exact_matches / total, 2)
    precision = (
        round(100.0 * exact_matches / placed_count, 2) if placed_count > 0 else 0.0
    )
    coverage = round(100.0 * exact_matches / total, 2)
    abstention_rate = round(100.0 * abstained_count / total, 2)

    return PlacementMetrics(
        total_evaluations=total,
        placement_accuracy=placement_accuracy,
        precision=precision,
        coverage=coverage,
        abstention_rate=abstention_rate,
        exact_matches=exact_matches,
        abstained_count=abstained_count,
    )
