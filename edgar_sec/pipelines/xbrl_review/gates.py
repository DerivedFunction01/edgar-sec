"""Gate evidence for XBRL review runs, composed from engine surfaces.

Battery and pair-gate outcomes are computed in-process from the engine's
review modules; the census outcome is scored from the standing census
summary with the engine's own expectations, never re-implemented here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from edgar_sec.engine.xbrl.discovery.cohort import load_canonical_union_cohort
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.review.battery import BATTERY_SET, evaluate_battery
from edgar_sec.engine.xbrl.review.benchmark import (
    CENSUS_EXPECTATIONS,
    PAIR_SET,
    evaluate_pairs,
    score_census,
)
from edgar_sec.engine.xbrl.review.relations import RELATION_SET, evaluate_relations
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.cohort_lookup import CohortLookup
from edgar_sec.engine.xbrl.solve.concept_table import build_cohort_table
from edgar_sec.engine.xbrl.solve.query import FinancialQueryEngine
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.pipelines.xbrl_review.bundles import (
    LoadedFiling,
    cohort_entries,
    load_filing,
)

ADJUDICATED_BATTERY_FAILURES = frozenset()


def _latest_undimensioned_fact(loaded: LoadedFiling, qname: str) -> XbrlFact:
    own = [
        fact
        for fact in loaded.facts
        if fact.concept_qname == qname and not fact.dimensions
    ]
    if not own:
        raise ValueError(f"no undimensioned fact {qname} in {loaded.accession}")
    return max(own, key=lambda fact: fact.instant_date or fact.end_date or "")


def _battery_evidence(taxonomy: Any) -> dict[str, Any]:
    seeds = {str(seed.accession): seed for seed in load_canonical_union_cohort()}
    endpoints: dict[str, tuple] = {}
    for entry in BATTERY_SET:
        if entry.accession not in endpoints:
            loaded = load_filing(seeds[entry.accession])
            endpoints[entry.accession] = (loaded.facts, loaded.calc_arcs)
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=taxonomy))
    )
    report = evaluate_battery(engine, endpoints)
    return {
        "total": report.total,
        "passed": report.passed,
        "failure_ids": [r.entry_id for r in report.results if not r.passed],
        "passed_all": report.passed_all,
    }


def _pair_gate_evidence(taxonomy: Any) -> dict[str, Any]:
    filings = load_canonical_union_cohort()
    entries = cohort_entries(filings)
    lookup = CohortLookup(build_cohort_table(taxonomy, entries), entries)
    try:
        by_firm_year = {(seed.firm.lower(), seed.fy): seed for seed in filings}
        source_facts = {}
        for spec in PAIR_SET:
            if spec.incompatibility:
                seed = by_firm_year[(spec.source_firm.lower(), 2024)]
                source_facts[(spec.source_firm, spec.target)] = (
                    _latest_undimensioned_fact(load_filing(seed), spec.target)
                )
        pairs = evaluate_pairs(lookup, PAIR_SET, source_facts)
    finally:
        lookup.close()
    seeds = {str(seed.accession): seed for seed in filings}
    endpoints = {}
    for spec in RELATION_SET:
        for accession in (spec.pre_accession, spec.post_accession):
            if accession not in endpoints:
                loaded = load_filing(seeds[accession])
                endpoints[accession] = (loaded.facts, loaded.calc_arcs)
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=taxonomy))
    )
    relations = evaluate_relations(engine, endpoints)
    return {
        "total": pairs.total + relations.total,
        "passed": pairs.passed + relations.passed,
        "failures": list(pairs.failures) + list(relations.failures),
        "passed_all": pairs.passed + relations.passed == pairs.total + relations.total,
    }


def _census_evidence(census_summary: dict[str, Any] | None) -> dict[str, Any]:
    if census_summary is None:
        return {"passed": False, "status": "not_recorded", "populations": {}}
    expected = {
        name: CENSUS_EXPECTATIONS[name]
        for name in census_summary.get("populations", {})
        if name in CENSUS_EXPECTATIONS
    }
    score = score_census(census_summary, expected)
    return {
        "passed": bool(score.passed),
        "status": "scored",
        "populations": census_summary.get("populations", {}),
        "failures": list(score.failures),
        "source": "tools/xbrl_census.py summary scored by engine benchmark",
    }


def compute_gate_evidence(
    census_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the three-gate evidence record for the canonical corpus."""
    taxonomy = load_domain_taxonomy()
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "battery": _battery_evidence(taxonomy),
        "pair_gate": _pair_gate_evidence(taxonomy),
        "census": _census_evidence(census_summary),
    }


def validate_gate_evidence(evidence: dict[str, Any] | None) -> None:
    """Refuse promotion unless the evidence carries three passing gates."""
    if not isinstance(evidence, dict):
        raise ValueError("promotion requires gate evidence; none was supplied")
    census = evidence.get("census") or {}
    if census.get("passed") is not True:
        raise ValueError("promotion refused: census gate evidence is not passing")
    pair_gate = evidence.get("pair_gate") or {}
    if not pair_gate.get("total") or pair_gate.get("passed") != pair_gate.get("total"):
        raise ValueError("promotion refused: pair gate evidence is not passing")
    battery = evidence.get("battery") or {}
    failures = set(battery.get("failure_ids") or battery.get("failures") or [])
    total = battery.get("total") or 0
    passed = battery.get("passed") or 0
    if (
        not total
        or passed < total - len(ADJUDICATED_BATTERY_FAILURES)
        or not failures.issubset(ADJUDICATED_BATTERY_FAILURES)
    ):
        raise ValueError(
            "promotion refused: battery evidence exceeds the adjudicated "
            "baseline (permitted failures: "
            + (", ".join(sorted(ADJUDICATED_BATTERY_FAILURES)) or "none")
            + ")"
        )


__all__ = [
    "ADJUDICATED_BATTERY_FAILURES",
    "compute_gate_evidence",
    "validate_gate_evidence",
]
