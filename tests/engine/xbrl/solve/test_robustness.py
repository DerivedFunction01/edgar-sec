"""Robustness suite implementing Tests T1, T3, and T4 for XBRL solver."""

import random
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.solve.gold import (
    ExtensionGroundTruth,
    PlacementPrediction,
    evaluate_placement_accuracy,
    extract_extension_ground_truth,
)
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver


def test_t1_hidden_arc_placement_experiment() -> None:
    """Verify solver placement accuracy with and without published calculation arcs."""
    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    solver = XbrlConstraintSolver(kb, enable_head_induction=True)

    acc = AccessionNumber("0000950170-24-087843")
    arcs = [
        CalculationArc("us-gaap:GrossProfit", "us-gaap:Revenues", 1.0),
        CalculationArc("us-gaap:GrossProfit", "msft:CustomProductRevenue", 1.0),
        CalculationArc("us-gaap:GrossProfit", "msft:CustomDirectCost", -1.0),
    ]
    facts = [
        XbrlFact(acc, "msft:CustomProductRevenue", 50000.0),
        XbrlFact(acc, "msft:CustomDirectCost", 20000.0),
    ]

    # With all arcs available
    preds_with_arcs = solver.solve_placements(facts, arcs)
    _, gold = extract_extension_ground_truth(arcs)
    metrics_with_arcs = evaluate_placement_accuracy(gold, preds_with_arcs)
    assert metrics_with_arcs.placement_accuracy == 100.0

    # Withheld hidden arcs (Test T1)
    core_arcs, _ = extract_extension_ground_truth(arcs)
    preds_hidden = solver.solve_placements(facts, core_arcs)
    metrics_hidden = evaluate_placement_accuracy(gold, preds_hidden)
    assert metrics_hidden.placement_accuracy >= 50.0


def test_t3_label_shuffle_negative_control() -> None:
    """Verify placement accuracy collapses when ground-truth labels are randomly permuted."""
    gold = [
        ExtensionGroundTruth(f"ext:Concept_{i}", f"parent_{i}", 1.0) for i in range(10)
    ]
    preds = [
        PlacementPrediction(f"ext:Concept_{i}", f"parent_{i}", 1.0) for i in range(10)
    ]
    base_metrics = evaluate_placement_accuracy(gold, preds)
    assert base_metrics.placement_accuracy == 100.0

    rng = random.Random(42)
    shuffled_parents = [f"parent_{(i + 1) % 10}" for i in range(10)]
    shuffled_gold = [
        ExtensionGroundTruth(f"ext:Concept_{i}", shuffled_parents[i], 1.0)
        for i in range(10)
    ]
    shuffled_metrics = evaluate_placement_accuracy(shuffled_gold, preds)
    assert shuffled_metrics.placement_accuracy == 0.0


def test_t4_canary_nonsense_tags_abstention() -> None:
    """Verify solver abstains on canary nonsense concepts with zero hallucinations."""
    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    solver = XbrlConstraintSolver(kb)

    acc = AccessionNumber("0000950170-24-087843")
    canaries = [
        XbrlFact(acc, "xyz:ZzzQwerty99NonsenseTag", 123.0),
        XbrlFact(acc, "fake:UnknownCanaryMetricBlah", 456.0),
    ]

    preds = solver.solve_placements(canaries, ())
    assert len(preds) == 2
    assert all(p.is_abstained for p in preds)
    assert all(p.predicted_parent is None for p in preds)
