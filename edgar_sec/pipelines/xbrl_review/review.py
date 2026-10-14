"""Review execution, case staging, and rule promotion for XBRL pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.counter_solver import CounterSolver
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.review.paths import ReviewPaths
from edgar_sec.pipelines.xbrl_review.paths import resolve_xbrl_review_paths


@dataclass(frozen=True, slots=True)
class ReviewHypothesis:
    """Hypothesis proposed by the counter-solver during an epistemic audit."""

    rule_id: str
    hypothesis_type: str
    target_concept: str
    source_concept: str
    algebraic_weight: float
    firm: str
    sector: str
    evidence_value: float | None = None


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """Record of an unconsumed fact placed in epistemic quarantine."""

    accession: str
    firm: str
    period: str
    concept_qname: str
    numeric_value: float | None
    target_residual: float | None
    candidate_parent: str | None
    correlation_score: float | None
    audit_status: str


@dataclass(frozen=True, slots=True)
class SolvedNodeRecord:
    """Record of an XBRL fact resolved by solver or subatomic decomposition."""

    accession: str
    firm: str
    cik: int
    period: str
    concept_qname: str
    prime_head: str
    modifiers_json: str
    resolution_tier: str
    reported_value: float | None
    derived_value: float | None
    derivation_path: str
    latency_ms: float


@dataclass(frozen=True, slots=True)
class ReviewRun:
    """Summary of a staged review run."""

    run_id: str
    run_dir: Path
    total_filings: int
    solved_count: int
    quarantine_count: int
    hypotheses_count: int


@dataclass(frozen=True, slots=True)
class PromotedRuleRecord:
    """Record of a candidate hypothesis rule promoted to the DuckDB knowledge base."""

    rule_id: str
    target_concept: str
    source_concept: str
    algebraic_weight: float
    scope_firm: str
    scope_sector: str
    promoted_at: str


def execute_review_generation(
    cohort_filings: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    output_root: Path | None = None,
) -> ReviewRun:
    """Execute solver and counter-solver on cohort and stage diagnostic cases."""
    now = datetime.now(timezone.utc)
    resolved_run_id = run_id or f"run-{now.strftime('%Y%m%d_%H%M%S')}"
    paths = resolve_xbrl_review_paths()
    paths.ensure_directories()
    if output_root is not None:
        run_dir = (
            output_root
            if output_root.name == resolved_run_id
            else output_root / resolved_run_id
        )
        review_paths = ReviewPaths(root=run_dir)
    else:
        review_paths = paths.review_run_paths(resolved_run_id)

    run_dir = review_paths.root
    run_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = review_paths.cases_dir
    cases_dir.mkdir(parents=True, exist_ok=True)
    staging_lake_dir = paths.staging_lake_dir
    staging_lake_dir.mkdir(parents=True, exist_ok=True)

    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    solver = XbrlConstraintSolver(kb)

    all_solved: list[SolvedNodeRecord] = []
    all_quarantine: list[QuarantineRecord] = []
    all_hypotheses: list[ReviewHypothesis] = []

    for item in cohort_filings:
        ticker = str(item.get("ticker", "UNKNOWN"))
        cik_val = int(item.get("cik", 0))
        acc_str = str(item.get("accession", "0000000000-00-000000"))
        acc = AccessionNumber(acc_str)
        period = str(item.get("period", item.get("fiscal_year", "FY")))
        sector = str(item.get("sector", "*"))

        raw_facts = item.get("facts", [])
        facts = [
            XbrlFact(
                accession=acc,
                concept_qname=f.get("concept", ""),
                value=float(f["value"]) if f.get("value") is not None else None,
                unit=f.get("unit", "USD"),
                context_id=period,
            )
            for f in raw_facts
        ]
        raw_arcs = item.get("calc_arcs", [])
        calc_arcs = [
            CalculationArc(
                parent_qname=a.get("parent", ""),
                child_qname=a.get("child", ""),
                weight=float(a.get("weight", 1.0)),
            )
            for a in raw_arcs
        ]

        preds = solver.solve_placements(facts, calc_arcs) if facts else []

        counter = CounterSolver(primary_solver=solver)
        target_goals = list(item.get("targets", {}).keys())
        outcome = counter.audit_filing(
            facts=facts,
            target_goals=target_goals,
            calculation_arcs=calc_arcs,
        )

        case_dir = cases_dir / acc_str
        case_dir.mkdir(parents=True, exist_ok=True)

        case_solved: list[SolvedNodeRecord] = []
        for p in preds:
            if not p.is_abstained:
                rep_fact = next(
                    (f for f in facts if f.concept_qname == p.concept_qname), None
                )
                rec = SolvedNodeRecord(
                    accession=acc_str,
                    firm=ticker,
                    cik=cik_val,
                    period=period,
                    concept_qname=p.concept_qname,
                    prime_head=p.predicted_parent or "H_UNKNOWN",
                    modifiers_json="[]",
                    resolution_tier="EVIDENCE_KB",
                    reported_value=rep_fact.value if rep_fact else None,
                    derived_value=rep_fact.value if rep_fact else None,
                    derivation_path=p.predicted_parent or "",
                    latency_ms=0.1,
                )
                case_solved.append(rec)
        all_solved.extend(case_solved)

        case_quarantine: list[QuarantineRecord] = [
            QuarantineRecord(
                accession=acc_str,
                firm=ticker,
                period=period,
                concept_qname=qf.fact.concept_qname,
                numeric_value=(
                    float(qf.fact.value)
                    if isinstance(qf.fact.value, (int, float))
                    else None
                ),
                target_residual=None,
                candidate_parent=None,
                correlation_score=None,
                audit_status="UNAUDITED",
            )
            for qf in outcome.quarantined_facts
        ]
        all_quarantine.extend(case_quarantine)

        case_hypotheses: list[ReviewHypothesis] = []
        for i, h in enumerate(outcome.hypotheses):
            hyp = ReviewHypothesis(
                rule_id=f"HYP_SHADOW_{acc_str}_{i}",
                hypothesis_type=h.hypothesis_type,
                target_concept=h.hypothesized_parent,
                source_concept=h.concept_qname,
                algebraic_weight=h.algebraic_weight,
                firm=ticker,
                sector=sector,
                evidence_value=h.residual_delta,
            )
            case_hypotheses.append(hyp)
        all_hypotheses.extend(case_hypotheses)

        atomic_write_json(
            case_dir / "solved_nodes.json",
            [asdict(s) for s in case_solved],
            indent=2,
        )
        atomic_write_json(
            case_dir / "epistemic_quarantine.json",
            [asdict(q) for q in case_quarantine],
            indent=2,
        )
        atomic_write_json(
            case_dir / "hypotheses.json",
            [asdict(h) for h in case_hypotheses],
            indent=2,
        )

    manifest_data = {
        "run_id": resolved_run_id,
        "created_at": now.isoformat(),
        "total_filings": len(cohort_filings),
        "total_solved_nodes": len(all_solved),
        "total_quarantined": len(all_quarantine),
        "total_hypotheses": len(all_hypotheses),
        "cases": [item.get("accession") for item in cohort_filings],
    }
    atomic_write_json(run_dir / "manifest.jsonl", manifest_data)

    return ReviewRun(
        run_id=resolved_run_id,
        run_dir=run_dir,
        total_filings=len(cohort_filings),
        solved_count=len(all_solved),
        quarantine_count=len(all_quarantine),
        hypotheses_count=len(all_hypotheses),
    )


def promote_review_rule(
    rule_id: str,
    run_dir: Path,
    *,
    db_path: Path | None = None,
) -> PromotedRuleRecord:
    """Promote an approved hypothesis rule to the target DuckDB database."""
    target_db = db_path or resolve_xbrl_review_paths().unification_rules_db_path
    target_db.parent.mkdir(parents=True, exist_ok=True)

    cases_dir = run_dir / "cases"
    matched_hyp: dict[str, Any] | None = None
    if cases_dir.is_dir():
        for case_p in cases_dir.iterdir():
            hyp_p = case_p / "hypotheses.json"
            if hyp_p.is_file():
                hyps = json.loads(hyp_p.read_text(encoding="utf-8"))
                for h in hyps:
                    if h.get("rule_id") == rule_id:
                        matched_hyp = h
                        break
            if matched_hyp is not None:
                break

    if matched_hyp is None:
        raise ValueError(f"Rule ID '{rule_id}' not found in review run {run_dir}")

    now = datetime.now(timezone.utc).isoformat()
    record = PromotedRuleRecord(
        rule_id=matched_hyp["rule_id"],
        target_concept=matched_hyp["target_concept"],
        source_concept=matched_hyp["source_concept"],
        algebraic_weight=float(matched_hyp["algebraic_weight"]),
        scope_firm=matched_hyp.get("firm", "*"),
        scope_sector=matched_hyp.get("sector", "*"),
        promoted_at=now,
    )

    con = connect(database=target_db)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS xbrl_unification_rules (
            rule_id VARCHAR PRIMARY KEY,
            target_concept VARCHAR,
            source_concept VARCHAR,
            algebraic_weight DOUBLE,
            scope_firm VARCHAR,
            scope_sector VARCHAR,
            promoted_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        INSERT OR REPLACE INTO xbrl_unification_rules
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            record.rule_id,
            record.target_concept,
            record.source_concept,
            record.algebraic_weight,
            record.scope_firm,
            record.scope_sector,
            record.promoted_at,
        ],
    )
    con.close()
    return record
