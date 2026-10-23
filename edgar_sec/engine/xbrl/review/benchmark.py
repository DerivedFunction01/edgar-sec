"""Multi-firm XBRL lattice verification and robustness testing engine."""

from __future__ import annotations

from collections import Counter
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
from edgar_sec.engine.xbrl.solve.equivalence import (
    EXACT,
    GENERALIZATION,
    NEAR,
    SPECIALIZATION,
)
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


def summarize_census(evaluations: list[dict]) -> dict:
    """Aggregate evaluations into the scored summary shape, per population."""
    by_pop: dict[str, list[dict]] = {}
    for ev in evaluations:
        by_pop.setdefault(ev["population"], []).append(ev)
    summary: dict = {"populations": {}}
    for pop, evs in by_pop.items():
        summary["populations"][pop] = {
            "n": len(evs),
            "classification": dict(Counter(e["classification"] for e in evs)),
            "replay_mismatches": sum(1 for e in evs if e["replay_mismatch"]),
            "surfaced_conflicts": [
                {
                    "firm": e["firm"],
                    "term": e["term"],
                    "mode": e["mode"],
                    "precision_duplicate": e.get("conflict_precision_duplicate"),
                }
                for e in evs
                if e["facade"]["status"] == "CONFLICT"
            ],
            "derived_artefacts": [
                {"firm": e["firm"], "term": e["term"], "mode": e["mode"]}
                for e in evs
                if e["facade"]["status"] == "DERIVED"
                and not e.get("derived_in_faithful_tier", True)
            ],
            "derived_faithful_no_reported": [
                {
                    "firm": e["firm"],
                    "term": e["term"],
                    "mode": e["mode"],
                    "value": e["facade"]["value"],
                }
                for e in evs
                if e["facade"]["status"] == "DERIVED"
                and e.get("derived_in_faithful_tier")
                and e.get("derived_has_reported_fact") is False
            ],
            "textblock_answer_evaluations": sum(
                1 for e in evs if e.get("textblock_candidates")
            ),
            "near_promotions": sum(1 for e in evs if e.get("near_promotion")),
            "near_guard_violations": [
                {"firm": e["firm"], "term": e["term"], "mode": e["mode"]}
                for e in evs
                if e.get("near_guard_violation")
            ],
            "shadowed_conflicts": {
                "total": sum(
                    1 for e in evs if e.get("shadowed_conflict_in_tiers") is not None
                ),
                "in_faithful_tiers": sum(
                    1 for e in evs if e.get("shadowed_conflict_in_tiers")
                ),
                "by_facade_status": dict(
                    Counter(
                        e["facade"]["status"]
                        for e in evs
                        if e.get("shadowed_conflict_in_tiers") is not None
                    )
                ),
            },
            "loose_revenue": [
                {
                    "firm": e["firm"],
                    "mode": e["mode"],
                    "status": e["facade"]["status"],
                    "value": e["facade"]["value"],
                    "bare_components": e.get("bare_revenue_components"),
                }
                for e in evs
                if e["term"] == "revenue"
            ],
        }
    return summary


@dataclass(frozen=True, slots=True)
class CensusExpectation:
    """Scored census counts for one population; movement needs adjudication."""

    n: int
    correct: int
    honest: int
    surfaced_conflicts: int


@dataclass(frozen=True, slots=True)
class CensusScore:
    """Gate outcome for a census summary against scored expectations."""

    passed: bool
    failures: tuple[str, ...]


CENSUS_EXPECTATIONS: dict[str, CensusExpectation] = {
    "probe": CensusExpectation(n=168, correct=92, honest=76, surfaced_conflicts=23),
    "span": CensusExpectation(n=189, correct=127, honest=62, surfaced_conflicts=33),
    "span-supplement": CensusExpectation(
        n=5, correct=0, honest=5, surfaced_conflicts=0
    ),
    "followup": CensusExpectation(
        n=1402, correct=706, honest=696, surfaced_conflicts=184
    ),
}

_ADVERSE_CLASSES = frozenset(
    {"wrong-span", "wrong-value", "refused", "unfaithful non-answer"}
)


def score_census(
    summary: dict[str, Any],
    expectations: dict[str, CensusExpectation] = CENSUS_EXPECTATIONS,
) -> CensusScore:
    """Score a census summary; any unadjudicated movement fails the gate."""
    failures: list[str] = []
    populations = summary.get("populations", {})
    for name, expected in expectations.items():
        pop = populations.get(name)
        if pop is None:
            failures.append(f"{name}: population missing from summary")
            continue
        if pop["n"] != expected.n:
            failures.append(f"{name}: n {pop['n']} != expected {expected.n}")
        counts = pop["classification"]
        adverse = {key: counts[key] for key in counts if key in _ADVERSE_CLASSES}
        if adverse:
            failures.append(f"{name}: adverse classifications {adverse}")
        correct = counts.get("correct", 0)
        honest = counts.get("honest-faithful", 0)
        if correct != expected.correct:
            failures.append(f"{name}: correct {correct} != expected {expected.correct}")
        if honest != expected.honest:
            failures.append(
                f"{name}: honest-faithful {honest} != expected {expected.honest}"
            )
        if pop["replay_mismatches"] != 0:
            failures.append(
                f"{name}: replay_mismatches {pop['replay_mismatches']} != 0"
            )
        surfaced = len(pop["surfaced_conflicts"])
        if surfaced != expected.surfaced_conflicts:
            failures.append(
                f"{name}: surfaced_conflicts {surfaced} "
                f"!= expected {expected.surfaced_conflicts}"
            )
        if pop["derived_artefacts"]:
            failures.append(f"{name}: derived artefacts {pop['derived_artefacts']}")
        if pop["near_guard_violations"]:
            failures.append(
                f"{name}: near guard violations {pop['near_guard_violations']}"
            )
        if pop["textblock_answer_evaluations"] != 0:
            failures.append(
                f"{name}: textblock answers {pop['textblock_answer_evaluations']} != 0"
            )
    return CensusScore(passed=not failures, failures=tuple(failures))


@dataclass(frozen=True, slots=True)
class PairSpec:
    """One seeded cross-firm pair with its rendered-text provenance."""

    target: str
    candidate: str
    tier: str
    provenance: str
    rule: str = ""
    direction: str = ""
    via_default: bool = False
    source_firm: str = ""
    candidate_firm: str = ""
    incompatibility: str = ""


@dataclass(frozen=True, slots=True)
class PairReport:
    """Gate outcome for the seeded pair set against the live lookup."""

    total: int
    passed: int
    failures: tuple[str, ...]

    @property
    def passed_all(self) -> bool:
        """True when every seeded pair holds at its expected tier."""
        return not self.failures


PAIR_SET: tuple[PairSpec, ...] = (
    PairSpec(
        "us-gaap:AccountsPayableCurrent",
        "us-gaap:AccountsPayableCurrent",
        EXACT,
        "Phase 3 Step 4 specimen: APC target, 28 same-qname pairs EXACT",
        rule="equality",
    ),
    PairSpec(
        "us-gaap:AccountsPayable",
        "us-gaap:AccountsPayableCurrent",
        NEAR,
        "Phase 3 Step 4 specimen: bare payables, current form ranked first",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:AccountsPayable",
        "us-gaap:AccruedLiabilitiesCurrent",
        NEAR,
        "Phase 3 Step 4 specimen: bare payables, accrued form via default",
        rule="via_default",
        via_default=True,
    ),
    PairSpec(
        "us-gaap:AccountsPayable",
        "us-gaap:LiabilitiesCurrent",
        NEAR,
        "Phase 3 Step 4 specimen: bare payables, total-current generalization",
        rule="via_default",
        direction=GENERALIZATION,
        via_default=True,
    ),
    PairSpec(
        "us-gaap:Revenues",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        NEAR,
        "Q3 probe Class 1: GIS headline 19,857.2M at this concept (text "
        "L3153); followup Step 2 Q-B pin carries it as the NEAR neighbour",
        rule="subsumption",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:Revenues",
        "us-gaap:RegulatedAndUnregulatedOperatingRevenue",
        NEAR,
        "Followup evidence S4 NEE: candidate is the presented operating "
        "revenues headline 24,753M (text L1889), confirming specimen",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:Revenues",
        "us-gaap:ContractWithCustomerLiabilityRevenueRecognized",
        NEAR,
        "Followup evidence S4 AAPL: 7,700M deferred-revenue recognition "
        "line (text L1246) against the 391,035M headline (text L667)",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:Revenues",
        "msft:ContractWithCustomerLiabilityRevenueDeferred",
        NEAR,
        "Followup evidence S4 MSFT: 148,701M deferral rollforward (text "
        "L3072) against the 245,122M headline (text L1580)",
        rule="subsumption",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:Revenues",
        "us-gaap:RevenueRemainingPerformanceObligation",
        NEAR,
        "Followup evidence S4 V: 4,100M performance-obligation backlog "
        "(text L1872) against net revenue 35,926M (text L789)",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:NetIncomeLoss",
        "us-gaap:NetIncomeLossAttributableToNoncontrollingInterest",
        NEAR,
        "Followup evidence S4 CAT/CF/FCX: noncontrolling-interest "
        "attribution lines (text CAT L1851, CF L1103, FCX L3765)",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:DerivativeLiabilities",
        "us-gaap:DerivativeFairValueOfDerivativeLiability",
        NEAR,
        "Followup evidence S4 APD/GIS: presented derivative-liability "
        "fair-value totals 93.6M / 72.0M (text APD L3250, GIS L4562)",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:DerivativeLiabilities",
        "us-gaap:DerivativeInstrumentsAndHedgesLiabilities",
        NEAR,
        "Followup evidence S4 CF: total derivative liabilities 3M "
        "(text L3312), confirming specimen",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:DerivativeLiabilities",
        "us-gaap:DerivativeLiabilitiesCurrent",
        NEAR,
        "Followup evidence S4 F: current slice 1,000M of a 1,900M total "
        "(text L4704); the tier is the specimen, the value is partial",
        rule="single_modifier_difference",
        direction=SPECIALIZATION,
    ),
    PairSpec(
        "us-gaap:AccountsPayableCurrent",
        "",
        "",
        "Phase 3 Step 4 specimen: MSFT payables source, every ASML "
        "match flagged unit-incompatible, none dropped",
        source_firm="MSFT",
        candidate_firm="ASML",
        incompatibility="unit",
    ),
)


def evaluate_pairs(
    lookup: Any,
    pairs: tuple[PairSpec, ...] = PAIR_SET,
    source_facts: Any = None,
) -> PairReport:
    """Evaluate seeded pairs through the cohort lookup; mismatches fail.

    Tier pairs read ranked tier/rule/direction from equivalents; fact
    pairs read compatibility from equivalent_facts over supplied facts.
    """
    failures: list[str] = []
    passed = 0
    for spec in pairs:
        label = f"{spec.target} -> {spec.candidate or spec.candidate_firm}"
        if spec.incompatibility:
            source = (source_facts or {}).get((spec.source_firm, spec.target))
            if source is None:
                failures.append(f"{label}: no source fact supplied")
                continue
            matches = [
                item
                for item in lookup.equivalent_facts(source)
                if item.firm == spec.candidate_firm
            ]
            ok = bool(matches) and all(
                not item.compatible and item.incompatibility == spec.incompatibility
                for item in matches
            )
            if ok:
                passed += 1
            else:
                failures.append(
                    f"{label}: expected all {spec.candidate_firm} matches "
                    f"flagged {spec.incompatibility}, got {len(matches)} matches"
                )
            continue
        hits = [
            item
            for item in lookup.equivalents(spec.target)
            if item.qname == spec.candidate
        ]
        if not hits:
            failures.append(f"{label}: candidate absent (expected {spec.tier})")
            continue
        actual = hits[0]
        ok = (
            actual.tier == spec.tier
            and (not spec.rule or actual.rule == spec.rule)
            and (not spec.direction or actual.direction == spec.direction)
            and actual.via_default == spec.via_default
        )
        if ok:
            passed += 1
        else:
            failures.append(
                f"{label}: expected tier={spec.tier} rule={spec.rule} "
                f"direction={spec.direction} via_default={spec.via_default}, "
                f"got tier={actual.tier} rule={actual.rule} "
                f"direction={actual.direction} via_default={actual.via_default}"
            )
    return PairReport(total=len(pairs), passed=passed, failures=tuple(failures))
