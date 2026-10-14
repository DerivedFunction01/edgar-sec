"""Multi-firm XBRL lattice verification and robustness testing engine."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from edgar_sec.engine.xbrl.discovery.cohort import SeedFiling, load_seed_cohort
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.infra.storage.atomic import atomic_write_json


@dataclass(frozen=True, slots=True)
class BenchmarkTestResult:
    """Result of a single benchmark test execution."""

    battery: str
    firm: str
    target: str
    passed: bool
    tier: str
    expected: Any
    actual: Any
    latency_ms: float
    message: str = ""


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Summary report across all benchmark batteries and firms."""

    total_tests: int
    passed_tests: int
    failed_tests: int
    accuracy_pct: float
    total_latency_ms: float
    firm_count: int
    tier_counts: dict[str, int]
    battery_stats: dict[str, dict[str, int]]
    results: tuple[BenchmarkTestResult, ...]

    def to_dict(self) -> dict[str, Any]:
        """Convert benchmark report to a JSON-serializable dictionary."""
        return {
            "summary": {
                "total_tests": self.total_tests,
                "passed_tests": self.passed_tests,
                "failed_tests": self.failed_tests,
                "accuracy_pct": self.accuracy_pct,
                "total_latency_ms": round(self.total_latency_ms, 2),
                "firm_count": self.firm_count,
            },
            "tier_counts": self.tier_counts,
            "battery_stats": self.battery_stats,
            "results": [
                {
                    "battery": r.battery,
                    "firm": r.firm,
                    "target": r.target,
                    "passed": r.passed,
                    "tier": r.tier,
                    "expected": r.expected,
                    "actual": r.actual,
                    "latency_ms": round(r.latency_ms, 3),
                    "message": r.message,
                }
                for r in self.results
            ],
        }


def _run_t1_identity(
    filing: SeedFiling,
    solver: XbrlConstraintSolver,
) -> list[BenchmarkTestResult]:
    """Execute T1 Identity Preservation battery for anchor facts."""
    results: list[BenchmarkTestResult] = []
    anchors = [
        ("Revenues", 1000.0),
        ("Assets", 5000.0),
        ("Liabilities", 2000.0),
        ("StockholdersEquity", 3000.0),
    ]
    facts = [
        XbrlFact(filing.accession, f"us-gaap:{name}", val, context_id=f"{filing.fy}-FY")
        for name, val in anchors
    ]

    for name, exp_val in anchors:
        t0 = time.perf_counter()
        agg = solver.evaluate_goal(f"us-gaap:{name}", facts)
        elapsed = (time.perf_counter() - t0) * 1000.0
        passed = (
            agg.resolution_tier == "DIRECT_ANCHOR"
            and agg.value is not None
            and abs(agg.value - exp_val) < 1e-4
        )
        results.append(
            BenchmarkTestResult(
                battery="T1",
                firm=filing.firm,
                target=name,
                passed=passed,
                tier=agg.resolution_tier,
                expected=exp_val,
                actual=agg.value,
                latency_ms=elapsed,
            )
        )
    return results


def _run_t2_subatomic(
    filing: SeedFiling,
    solver: XbrlConstraintSolver,
) -> list[BenchmarkTestResult]:
    """Execute T2 Multi-Hop Subatomic Derivations without aggregate anchors."""
    results: list[BenchmarkTestResult] = []
    acc = filing.accession
    period = f"{filing.fy}-FY"

    # Base granular facts
    facts = [
        XbrlFact(acc, "us-gaap:Revenues", 200.0, context_id=period),
        XbrlFact(acc, "us-gaap:CostOfGoodsAndServicesSold", 80.0, context_id=period),
        XbrlFact(acc, "us-gaap:OperatingExpenses", 50.0, context_id=period),
        XbrlFact(acc, "us-gaap:AssetsCurrent", 600.0, context_id=period),
        XbrlFact(acc, "us-gaap:AssetsNoncurrent", 400.0, context_id=period),
        XbrlFact(acc, "us-gaap:Liabilities", 450.0, context_id=period),
        XbrlFact(acc, "us-gaap:StockholdersEquity", 550.0, context_id=period),
        XbrlFact(
            acc,
            "us-gaap:NetCashProvidedByUsedInOperatingActivities",
            300.0,
            context_id=period,
        ),
        XbrlFact(
            acc,
            "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
            75.0,
            context_id=period,
        ),
        XbrlFact(acc, "us-gaap:NetIncomeLoss", 70.0, context_id=period),
        XbrlFact(
            acc,
            "us-gaap:OtherComprehensiveIncomeLossNetOfTax",
            10.0,
            context_id=period,
        ),
    ]

    derivations = [
        ("GrossProfit", 120.0),
        ("OperatingIncomeLoss", 70.0),
        ("Assets", 1000.0),
        ("LiabilitiesAndStockholdersEquity", 1000.0),
        ("FreeCashFlow", 225.0),
        ("ComprehensiveIncomeNetOfTax", 80.0),
    ]

    for target, exp_val in derivations:
        t0 = time.perf_counter()
        agg = solver.evaluate_goal(target, facts)
        elapsed = (time.perf_counter() - t0) * 1000.0
        passed = (
            agg.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"
            and agg.value is not None
            and abs(agg.value - exp_val) < 1e-4
        )
        results.append(
            BenchmarkTestResult(
                battery="T2",
                firm=filing.firm,
                target=target,
                passed=passed,
                tier=agg.resolution_tier,
                expected=exp_val,
                actual=agg.value,
                latency_ms=elapsed,
            )
        )
    return results


def _run_t3_cross_period(
    filing: SeedFiling,
    solver: XbrlConstraintSolver,
) -> list[BenchmarkTestResult]:
    """Execute T3 Cross-Period Consistency battery."""
    results: list[BenchmarkTestResult] = []
    acc = filing.accession
    p_cur = f"{filing.fy}-FY"
    p_prev = f"{filing.fy - 1}-FY"

    facts_cur = [
        XbrlFact(acc, "us-gaap:AssetsCurrent", 500.0, context_id=p_cur),
        XbrlFact(acc, "us-gaap:AssetsNoncurrent", 300.0, context_id=p_cur),
    ]
    facts_prev = [
        XbrlFact(acc, "us-gaap:AssetsCurrent", 450.0, context_id=p_prev),
        XbrlFact(acc, "us-gaap:AssetsNoncurrent", 250.0, context_id=p_prev),
    ]

    for period_label, facts, exp_val in [
        (p_cur, facts_cur, 800.0),
        (p_prev, facts_prev, 700.0),
    ]:
        t0 = time.perf_counter()
        agg = solver.evaluate_goal("Assets", facts, period=period_label)
        elapsed = (time.perf_counter() - t0) * 1000.0
        passed = (
            agg.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"
            and agg.value is not None
            and abs(agg.value - exp_val) < 1e-4
        )
        results.append(
            BenchmarkTestResult(
                battery="T3",
                firm=filing.firm,
                target=f"Assets_{period_label}",
                passed=passed,
                tier=agg.resolution_tier,
                expected=exp_val,
                actual=agg.value,
                latency_ms=elapsed,
            )
        )
    return results


def _run_t4_noise_immunity(
    filing: SeedFiling,
    solver: XbrlConstraintSolver,
) -> list[BenchmarkTestResult]:
    """Execute T4 Adversarial Noise and False-Positive Immunity battery."""
    results: list[BenchmarkTestResult] = []
    acc = filing.accession
    canary_tags = [
        "us-gaap:FooBarNonsenseSpecializedMetric",
        "custom:CanaryInventedMetricWithoutBasis",
        "custom:VendorSyntheticAdHocCharge",
    ]
    facts = [XbrlFact(acc, tag, 999.0) for tag in canary_tags]

    t0 = time.perf_counter()
    preds = solver.solve_placements(facts)
    elapsed = (time.perf_counter() - t0) * 1000.0
    for pred in preds:
        passed = pred.is_abstained and pred.predicted_parent is None
        results.append(
            BenchmarkTestResult(
                battery="T4",
                firm=filing.firm,
                target=f"placement_{pred.concept_qname.split(':')[-1]}",
                passed=passed,
                tier="ABSTAINED" if passed else "FALSE_POSITIVE",
                expected="ABSTAINED",
                actual="ABSTAINED" if pred.is_abstained else pred.predicted_parent,
                latency_ms=elapsed / max(len(preds), 1),
            )
        )

    for tag in canary_tags:
        t0 = time.perf_counter()
        agg = solver.evaluate_goal(tag, [])
        elapsed = (time.perf_counter() - t0) * 1000.0
        passed = agg.resolution_tier == "UNRESOLVED" and agg.value is None
        results.append(
            BenchmarkTestResult(
                battery="T4",
                firm=filing.firm,
                target=f"goal_{tag.split(':')[-1]}",
                passed=passed,
                tier=agg.resolution_tier,
                expected=None,
                actual=agg.value,
                latency_ms=elapsed,
            )
        )
    return results


def run_benchmark(
    cohort: Sequence[SeedFiling],
    solver: XbrlConstraintSolver,
) -> BenchmarkReport:
    """Run all benchmark batteries across the given cohort filings."""
    all_results: list[BenchmarkTestResult] = []
    t_start = time.perf_counter()

    for filing in cohort:
        all_results.extend(_run_t1_identity(filing, solver))
        all_results.extend(_run_t2_subatomic(filing, solver))
        all_results.extend(_run_t3_cross_period(filing, solver))
        all_results.extend(_run_t4_noise_immunity(filing, solver))

    total_elapsed = (time.perf_counter() - t_start) * 1000.0
    total = len(all_results)
    passed = sum(1 for r in all_results if r.passed)
    failed = total - passed
    acc_pct = round((passed / total * 100.0) if total else 0.0, 2)

    tier_counts: dict[str, int] = {}
    battery_stats: dict[str, dict[str, int]] = {}
    for r in all_results:
        tier_counts[r.tier] = tier_counts.get(r.tier, 0) + 1
        b_entry = battery_stats.setdefault(r.battery, {"total": 0, "passed": 0})
        b_entry["total"] += 1
        if r.passed:
            b_entry["passed"] += 1

    return BenchmarkReport(
        total_tests=total,
        passed_tests=passed,
        failed_tests=failed,
        accuracy_pct=acc_pct,
        total_latency_ms=total_elapsed,
        firm_count=len(cohort),
        tier_counts=tier_counts,
        battery_stats=battery_stats,
        results=tuple(all_results),
    )


def execute_cohort_benchmark(
    cohort_source: Path,
    taxonomy_dir: Path | None = None,
    output_path: Path | None = None,
) -> BenchmarkReport:
    """Load cohort and taxonomy, execute benchmark batteries, and write report."""
    cohort = load_seed_cohort(cohort_source)
    tax = load_domain_taxonomy(taxonomy_dir)
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    solver = XbrlConstraintSolver(kb)

    report = run_benchmark(cohort, solver)
    if output_path is not None:
        atomic_write_json(output_path, report.to_dict(), indent=2)
    return report
