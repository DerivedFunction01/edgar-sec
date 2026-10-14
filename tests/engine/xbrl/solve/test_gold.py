"""Unit tests for independent gold ground truth and hidden-arc evaluation."""

from edgar_sec.engine.xbrl.solve.gold import (
    ExtensionGroundTruth,
    PlacementPrediction,
    evaluate_placement_accuracy,
    extract_extension_ground_truth,
    is_extension_concept,
)
from edgar_sec.engine.xbrl.schema.models import CalculationArc


def test_is_extension_concept() -> None:
    """Verify standard US-GAAP vs custom extension concept detection."""
    assert not is_extension_concept("us-gaap:Revenues")
    assert not is_extension_concept("dei:EntityCommonStockSharesOutstanding")
    assert not is_extension_concept("srt:ProductOrServiceAxis")
    assert is_extension_concept("msft:ServerProductsAndCloudServicesMember")
    assert is_extension_concept("aapl:ServicesMember")


def test_extract_extension_ground_truth() -> None:
    """Verify calculation arc partitioning into core baseline and gold."""
    arcs = [
        CalculationArc(
            parent_qname="us-gaap:GrossProfit",
            child_qname="us-gaap:Revenues",
            weight=1.0,
        ),
        CalculationArc(
            parent_qname="us-gaap:GrossProfit",
            child_qname="msft:CustomProductRevenue",
            weight=1.0,
        ),
    ]

    core, gold = extract_extension_ground_truth(arcs)
    assert len(core) == 1
    assert core[0].child_qname == "us-gaap:Revenues"

    assert len(gold) == 1
    assert gold[0].concept_qname == "msft:CustomProductRevenue"
    assert gold[0].parent_node == "us-gaap:GrossProfit"
    assert gold[0].weight == 1.0


def test_evaluate_placement_accuracy_metrics() -> None:
    """Verify Rule M4 placement accuracy and precision computations."""
    gold = [
        ExtensionGroundTruth("msft:ExtA", "us-gaap:GrossProfit", 1.0),
        ExtensionGroundTruth("msft:ExtB", "us-gaap:OperatingExpenses", -1.0),
        ExtensionGroundTruth("msft:ExtC", "us-gaap:NonoperatingIncome", 1.0),
    ]

    predictions = [
        PlacementPrediction("msft:ExtA", "us-gaap:GrossProfit", 1.0),
        PlacementPrediction("msft:ExtB", "us-gaap:GrossProfit", -1.0),  # Wrong parent
        PlacementPrediction("msft:ExtC", None, None, is_abstained=True),  # Abstained
    ]

    metrics = evaluate_placement_accuracy(gold, predictions)
    assert metrics.total_evaluations == 3
    assert metrics.exact_matches == 1
    assert metrics.abstained_count == 1
    assert metrics.placement_accuracy == 33.33
    assert metrics.precision == 50.0
    assert metrics.abstention_rate == 33.33
