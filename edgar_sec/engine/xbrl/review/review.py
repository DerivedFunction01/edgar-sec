"""Review and staging engine for XBRL semantic lattice learning."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.solve.counter_solver import CounterSolver
from edgar_sec.engine.xbrl.storage.database import (
    QuarantineRecord,
    SolvedNodeRecord,
    UnificationRuleRecord,
    export_table_to_parquet,
    init_xbrl_database,
    insert_quarantined_facts,
    insert_solved_nodes,
    upsert_unification_rule,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.review.paths import ReviewPaths


@dataclass(frozen=True, slots=True)
class ReviewHypothesis:
    """Induced candidate unification rule or netting hypothesis."""

    rule_id: str
    hypothesis_type: str
    target_concept: str
    source_concept: str
    algebraic_weight: float
    firm: str
    sector: str
    evidence_value: float


@dataclass(frozen=True, slots=True)
class ReviewRun:
    """Summary record for a staged review execution."""

    run_id: str
    run_dir: Path
    timestamp: str
    total_filings: int
    total_solved_nodes: int
    total_quarantined_facts: int
    total_hypotheses: int


def execute_review_generation(
    cohort_filings: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    output_root: Path | None = None,
) -> ReviewRun:
    """Execute solver and counter-solver on cohort and stage diagnostic cases."""
    now = datetime.now(timezone.utc)
    resolved_run_id = run_id or f"run-{now.strftime('%Y%m%d_%H%M%S')}"
    paths = resolve_xbrl_paths()
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
        year = str(item.get("fiscal_year", "*"))

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

    con = connect(database=":memory:")
    init_xbrl_database(con)
    insert_solved_nodes(con, all_solved)
    insert_quarantined_facts(con, all_quarantine)

    export_table_to_parquet(
        con, "xbrl_solved_nodes", staging_lake_dir / "solved_nodes.parquet"
    )
    export_table_to_parquet(
        con,
        "xbrl_epistemic_quarantine",
        staging_lake_dir / "epistemic_quarantine.parquet",
    )
    con.close()

    manifest_lines = [
        json.dumps(
            {
                "run_id": resolved_run_id,
                "timestamp": now.isoformat(),
                "total_filings": len(cohort_filings),
                "total_solved_nodes": len(all_solved),
                "total_quarantined_facts": len(all_quarantine),
                "total_hypotheses": len(all_hypotheses),
            }
        )
    ]
    manifest_path = run_dir / "manifest.jsonl"
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    return ReviewRun(
        run_id=resolved_run_id,
        run_dir=run_dir,
        timestamp=now.isoformat(),
        total_filings=len(cohort_filings),
        total_solved_nodes=len(all_solved),
        total_quarantined_facts=len(all_quarantine),
        total_hypotheses=len(all_hypotheses),
    )


def compare_review_runs(base_run_dir: Path, new_run_dir: Path) -> dict[str, Any]:
    """Compare two review runs and report solved node and residual deltas."""
    base_manifest = json.loads(
        (base_run_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    new_manifest = json.loads(
        (new_run_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )

    base_cases = {p.name: p for p in (base_run_dir / "cases").iterdir() if p.is_dir()}
    new_cases = {p.name: p for p in (new_run_dir / "cases").iterdir() if p.is_dir()}

    base_solved_concepts: set[str] = set()
    for c_dir in base_cases.values():
        sn_p = c_dir / "solved_nodes.json"
        if sn_p.is_file():
            data = json.loads(sn_p.read_text(encoding="utf-8"))
            base_solved_concepts.update(row["concept_qname"] for row in data)

    new_solved_concepts: set[str] = set()
    for c_dir in new_cases.values():
        sn_p = c_dir / "solved_nodes.json"
        if sn_p.is_file():
            data = json.loads(sn_p.read_text(encoding="utf-8"))
            new_solved_concepts.update(row["concept_qname"] for row in data)

    newly_solved = sorted(new_solved_concepts - base_solved_concepts)
    regressions = sorted(base_solved_concepts - new_solved_concepts)

    return {
        "base_run_id": base_manifest.get("run_id"),
        "new_run_id": new_manifest.get("run_id"),
        "delta_solved_nodes": (
            new_manifest.get("total_solved_nodes", 0)
            - base_manifest.get("total_solved_nodes", 0)
        ),
        "delta_quarantined_facts": (
            new_manifest.get("total_quarantined_facts", 0)
            - base_manifest.get("total_quarantined_facts", 0)
        ),
        "newly_solved_concepts": newly_solved,
        "regressed_concepts": regressions,
    }


def promote_review_rule(
    rule_id: str,
    run_dir: Path,
    *,
    db_path: Path | None = None,
) -> UnificationRuleRecord:
    """Promote an audited candidate hypothesis into the unification knowledge base."""
    found_hyp: ReviewHypothesis | None = None
    cases_dir = run_dir / "cases"
    for c_dir in cases_dir.iterdir():
        hyp_p = c_dir / "hypotheses.json"
        if hyp_p.is_file():
            data = json.loads(hyp_p.read_text(encoding="utf-8"))
            for h in data:
                if h["rule_id"] == rule_id:
                    found_hyp = ReviewHypothesis(**h)
                    break
        if found_hyp is not None:
            break

    if found_hyp is None:
        raise KeyError(f"Rule ID {rule_id} not found in review run {run_dir}")

    rule_rec = UnificationRuleRecord(
        rule_id=found_hyp.rule_id,
        target_concept=found_hyp.target_concept,
        source_concept=found_hyp.source_concept,
        algebraic_weight=found_hyp.algebraic_weight,
        scope_firm=found_hyp.firm,
        scope_sector=found_hyp.sector,
        scope_year="*",
        n_support=1,
        n_eligible=1,
        laplace_confidence=0.66,
        is_frozen=True,
    )

    target_db = (
        db_path
        if db_path is not None
        else resolve_xbrl_paths().unification_rules_db_path
    )
    con = connect(database=target_db)
    init_xbrl_database(con)
    upsert_unification_rule(con, rule_rec)
    con.close()
    return rule_rec
