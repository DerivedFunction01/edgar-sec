"""Review execution, case staging, and rule promotion for XBRL pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.discovery.cohort import SeedFiling
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.concept_table import build_cohort_table
from edgar_sec.engine.xbrl.solve.counter_solver import (
    CounterSolver,
    QuarantinedFact,
)
from edgar_sec.engine.xbrl.solve.evidence_index import (
    FilingEvidenceRecord,
    build_evidence_index,
)
from edgar_sec.engine.xbrl.solve.solver import SOLVER_FINGERPRINT, XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.taxonomy.domain import (
    DomainTaxonomy,
    load_domain_taxonomy,
)
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.parquet import write_parquet_table
from edgar_sec.infra.storage.review.paths import ReviewPaths
from edgar_sec.pipelines.xbrl_review.bundles import (
    LoadedFiling,
    cohort_entries,
    load_filing,
    missing_bundles,
    registry_filings,
)
from edgar_sec.pipelines.xbrl_review.gates import validate_gate_evidence
from edgar_sec.pipelines.xbrl_review.paths import (
    CALCULATION_ARCS_FILE,
    HYPOTHESES_FILE,
    PRESENTATION_ARCS_FILE,
    QUARANTINE_FILE,
    RULE_TRACE_FILE,
    SOLVED_NODES_FILE,
    xbrl_paths,
)
from edgar_sec.pipelines.xbrl_review.schemas import (
    CALCULATION_ARCS_SCHEMA,
    HYPOTHESES_SCHEMA,
    PRESENTATION_ARCS_SCHEMA,
    QUARANTINE_SCHEMA,
    RULE_TRACE_SCHEMA,
    SOLVED_NODES_SCHEMA,
)


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
    period: str = ""
    evidence_value: float | None = None


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """One quarantined pair; period/value are the representative fact's."""

    accession: str
    firm: str
    period: str
    concept_qname: str
    numeric_value: float | None
    reason: str
    fact_count: int


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
class RuleTraceRecord:
    """Record of one rule or audit outcome traced during a filing solve."""

    accession: str
    rule_id: str
    status: str
    lhs_value: float | None
    rhs_value: float | None
    discrepancy: float | None
    evidence_nodes: str


@dataclass(frozen=True, slots=True)
class PresentationArcRecord:
    """One presentation arc carried from a filing's bundle into the snapshot."""

    accession: str
    parent_qname: str
    child_qname: str
    order: float | None
    role_uri: str | None


@dataclass(frozen=True, slots=True)
class CalculationArcRecord:
    """One calculation arc carried from a filing's bundle into the snapshot."""

    accession: str
    parent_qname: str
    child_qname: str
    weight: float
    order: float | None
    role_uri: str | None


@dataclass(frozen=True, slots=True)
class FilingSolveResult:
    """All staged records produced by solving one filing."""

    solved: tuple[SolvedNodeRecord, ...]
    quarantine: tuple[QuarantineRecord, ...]
    hypotheses: tuple[ReviewHypothesis, ...]
    rule_trace: tuple[RuleTraceRecord, ...]
    presentation_arcs: tuple[PresentationArcRecord, ...] = ()
    calculation_arcs: tuple[CalculationArcRecord, ...] = ()


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


def _period_label(fact: XbrlFact) -> str:
    if fact.instant_date:
        return str(fact.instant_date)
    if fact.start_date or fact.end_date:
        return f"{fact.start_date or ''}/{fact.end_date or ''}"
    return ""


def _quarantine_representative_key(fact: XbrlFact) -> tuple:
    """Total order choosing a pair's representative fact deterministically."""
    return (
        bool(fact.dimensions),
        _period_label(fact),
        float(fact.value) if isinstance(fact.value, (int, float)) else float("inf"),
        fact.unit or "",
        tuple(sorted(fact.dimensions.items())),
        fact.context_id or "",
    )


def _quarantine_record(
    accession: str, firm: str, members: list[QuarantinedFact]
) -> QuarantineRecord:
    """Collapse one pair's quarantined facts to its representative record."""
    representative = min(
        members, key=lambda entry: _quarantine_representative_key(entry.fact)
    )
    fact = representative.fact
    return QuarantineRecord(
        accession=accession,
        firm=firm,
        period=_period_label(fact),
        concept_qname=fact.concept_qname,
        numeric_value=(
            float(fact.value) if isinstance(fact.value, (int, float)) else None
        ),
        reason=representative.reason,
        fact_count=len(members),
    )


def _representative_facts(facts: tuple[XbrlFact, ...]) -> dict[str, XbrlFact]:
    """Index each qname's representative fact in one pass over the facts.

    The representative is the first fact attaining the minimum of
    (dimensioned, non-numeric), exactly the per-qname scan's choice.
    """
    representatives: dict[str, XbrlFact] = {}
    keys: dict[str, tuple[bool, bool]] = {}
    for fact in facts:
        key = (bool(fact.dimensions), not isinstance(fact.value, (int, float)))
        current = keys.get(fact.concept_qname)
        if current is None or key < current:
            representatives[fact.concept_qname] = fact
            keys[fact.concept_qname] = key
    return representatives


def _audit_targets(loaded: LoadedFiling) -> list[str]:
    reported = {
        fact.concept_qname
        for fact in loaded.facts
        if not fact.dimensions and isinstance(fact.value, (int, float))
    }
    return sorted(
        {arc.parent_qname for arc in loaded.calc_arcs if arc.parent_qname in reported}
    )


def _dimensional_audit_targets(loaded: LoadedFiling) -> list[str]:
    undimensioned = {
        fact.concept_qname
        for fact in loaded.facts
        if not fact.dimensions and isinstance(fact.value, (int, float))
    }
    dimensioned = {
        fact.concept_qname
        for fact in loaded.facts
        if fact.dimensions and isinstance(fact.value, (int, float))
    }
    return sorted(
        {
            arc.parent_qname
            for arc in loaded.calc_arcs
            if arc.parent_qname in dimensioned and arc.parent_qname not in undimensioned
        }
    )


def _anchored_audit_targets(loaded: LoadedFiling) -> list[str]:
    undimensioned = {
        fact.concept_qname
        for fact in loaded.facts
        if not fact.dimensions and isinstance(fact.value, (int, float))
    }
    dimensioned = {
        fact.concept_qname
        for fact in loaded.facts
        if fact.dimensions and isinstance(fact.value, (int, float))
    }
    return sorted(undimensioned & dimensioned)


def solve_filing(
    loaded: LoadedFiling,
    *,
    solver: XbrlConstraintSolver,
    counter: CounterSolver,
    tokenizer: ConceptTokenizer,
    evidence_record: FilingEvidenceRecord | None = None,
) -> FilingSolveResult:
    """Solve one loaded filing into solved, quarantine, and hypothesis records."""
    seed = loaded.seed
    accession = loaded.accession
    started = time.perf_counter()
    predictions = solver.solve_placements(
        loaded.facts,
        loaded.calc_arcs,
        firm=seed.firm,
        sector=seed.sector,
        year=seed.fy,
    )
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)

    representatives = _representative_facts(loaded.facts)
    atoms: dict[str, Atom] = {}
    solved: list[SolvedNodeRecord] = []
    for prediction in predictions:
        if prediction.is_abstained:
            continue
        fact = representatives.get(prediction.concept_qname)
        atom = atoms.get(prediction.concept_qname)
        if atom is None:
            evidence = (
                evidence_record.evidence_context(prediction.concept_qname)
                if evidence_record is not None
                else None
            )
            atom = tokenizer.tokenize(
                prediction.concept_qname,
                loaded.declarations.get(prediction.concept_qname),
                evidence,
            ).atom
            atoms[prediction.concept_qname] = atom
        solved.append(
            SolvedNodeRecord(
                accession=accession,
                firm=seed.firm,
                cik=int(seed.cik),
                period=_period_label(fact) if fact is not None else "",
                concept_qname=prediction.concept_qname,
                prime_head=atom.head,
                modifiers_json=canonical_json(sorted(atom.modifiers)),
                resolution_tier=(
                    "SOLVER_PLACEMENT" if prediction.predicted_parent else "ATOM"
                ),
                reported_value=(
                    float(fact.value)
                    if fact is not None and isinstance(fact.value, (int, float))
                    else None
                ),
                derived_value=None,
                derivation_path=prediction.predicted_parent or "",
                latency_ms=latency_ms,
            )
        )

    outcome = counter.audit_filing(
        facts=loaded.facts,
        target_goals=_audit_targets(loaded),
        calculation_arcs=loaded.calc_arcs,
        dimensional_target_goals=_dimensional_audit_targets(loaded),
        anchored_target_goals=_anchored_audit_targets(loaded),
        declarations=loaded.declarations,
    )
    grouped: dict[str, list[QuarantinedFact]] = {}
    for entry in outcome.quarantined_facts:
        grouped.setdefault(entry.fact.concept_qname, []).append(entry)
    quarantine = tuple(
        _quarantine_record(accession, seed.firm, grouped[qname])
        for qname in sorted(grouped)
    )
    hypotheses = tuple(
        ReviewHypothesis(
            rule_id=f"HYP_RESIDUAL_{accession}_{index}",
            hypothesis_type=hypothesis.hypothesis_type,
            target_concept=hypothesis.hypothesized_parent,
            source_concept=hypothesis.concept_qname,
            algebraic_weight=hypothesis.algebraic_weight,
            firm=seed.firm,
            sector=seed.sector,
            period=hypothesis.period,
            evidence_value=hypothesis.residual_delta,
        )
        for index, hypothesis in enumerate(outcome.hypotheses)
    )
    rule_trace = tuple(
        RuleTraceRecord(
            accession=accession,
            rule_id=hypothesis.rule_id,
            status="HYPOTHESIZED",
            lhs_value=hypothesis.evidence_value,
            rhs_value=None,
            discrepancy=hypothesis.evidence_value,
            evidence_nodes=hypothesis.source_concept,
        )
        for hypothesis in hypotheses
    )
    return FilingSolveResult(
        solved=tuple(solved),
        quarantine=quarantine,
        hypotheses=hypotheses,
        rule_trace=rule_trace,
        presentation_arcs=tuple(
            PresentationArcRecord(
                accession=accession,
                parent_qname=arc.parent_qname,
                child_qname=arc.child_qname,
                order=arc.order,
                role_uri=arc.role_uri,
            )
            for arc in loaded.pres_arcs
        ),
        calculation_arcs=tuple(
            CalculationArcRecord(
                accession=accession,
                parent_qname=arc.parent_qname,
                child_qname=arc.child_qname,
                weight=arc.weight,
                order=arc.order,
                role_uri=arc.role_uri,
            )
            for arc in loaded.calc_arcs
        ),
    )


def build_engine_stack(
    filings: tuple[SeedFiling, ...],
) -> tuple[DomainTaxonomy, XbrlConstraintSolver, CounterSolver, ConceptTokenizer, int]:
    """Build solver, counter-solver, and tokenizer over one shared taxonomy.

    The knowledge base is pre-loaded with any rules already promoted into
    the unification rules database, so a promotion affects later runs.
    """
    taxonomy = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=taxonomy)
    promoted_loaded = 0
    rules_db = xbrl_paths().unification_rules_db_path
    if rules_db.is_file():
        promoted_loaded = kb.load_promoted_rules(rules_db)
    solver = XbrlConstraintSolver(kb)
    return (
        taxonomy,
        solver,
        CounterSolver(solver),
        ConceptTokenizer(taxonomy),
        (promoted_loaded),
    )


def _resolve_filings(cohort_filings: list[dict[str, Any]]) -> tuple[SeedFiling, ...]:
    registry = {str(seed.accession): seed for seed in registry_filings()}
    seeds: list[SeedFiling] = []
    for row in cohort_filings:
        accession = str(row.get("accession", ""))
        seed = registry.get(accession)
        if seed is None:
            seed = SeedFiling.from_dict(row)
        seeds.append(seed)
    missing = missing_bundles([str(seed.accession) for seed in seeds])
    if missing:
        raise ValueError("no bundle on disk for accession(s): " + ", ".join(missing))
    return tuple(seeds)


def _write_case(case_dir: Path, result: FilingSolveResult) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    write_parquet_table(
        pa.Table.from_pylist(
            [asdict(record) for record in result.solved], schema=SOLVED_NODES_SCHEMA
        ),
        case_dir / SOLVED_NODES_FILE,
    )
    write_parquet_table(
        pa.Table.from_pylist(
            [asdict(record) for record in result.quarantine],
            schema=QUARANTINE_SCHEMA,
        ),
        case_dir / QUARANTINE_FILE,
    )
    write_parquet_table(
        pa.Table.from_pylist(
            [asdict(record) for record in result.hypotheses],
            schema=HYPOTHESES_SCHEMA,
        ),
        case_dir / HYPOTHESES_FILE,
    )
    write_parquet_table(
        pa.Table.from_pylist(
            [asdict(record) for record in result.rule_trace],
            schema=RULE_TRACE_SCHEMA,
        ),
        case_dir / RULE_TRACE_FILE,
    )
    write_parquet_table(
        pa.Table.from_pylist(
            [asdict(record) for record in result.presentation_arcs],
            schema=PRESENTATION_ARCS_SCHEMA,
        ),
        case_dir / PRESENTATION_ARCS_FILE,
    )
    write_parquet_table(
        pa.Table.from_pylist(
            [asdict(record) for record in result.calculation_arcs],
            schema=CALCULATION_ARCS_SCHEMA,
        ),
        case_dir / CALCULATION_ARCS_FILE,
    )


def execute_review_generation(
    cohort_filings: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    output_root: Path | None = None,
    gate_evidence: dict[str, Any] | None = None,
) -> ReviewRun:
    """Execute solver and counter-solver over bundle-loaded cohort filings."""
    now = datetime.now(timezone.utc)
    resolved_run_id = run_id or f"run-{now.strftime('%Y%m%d_%H%M%S')}"
    paths = xbrl_paths()
    if output_root is not None:
        run_dir = (
            output_root
            if output_root.name == resolved_run_id
            else output_root / resolved_run_id
        )
        review_paths = ReviewPaths(root=run_dir)
    else:
        review_paths = paths.review_paths(resolved_run_id)

    run_dir = review_paths.root
    run_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = review_paths.cases_dir
    cases_dir.mkdir(parents=True, exist_ok=True)

    seeds = _resolve_filings(cohort_filings)
    taxonomy, solver, counter, tokenizer, promoted_loaded = build_engine_stack(seeds)
    entries = cohort_entries(seeds)
    evidence_index = build_evidence_index(
        entries, build_cohort_table(taxonomy, entries)
    )

    all_solved: list[SolvedNodeRecord] = []
    all_quarantine: list[QuarantineRecord] = []
    all_hypotheses: list[ReviewHypothesis] = []
    for seed in seeds:
        loaded = load_filing(seed)
        result = solve_filing(
            loaded,
            solver=solver,
            counter=counter,
            tokenizer=tokenizer,
            evidence_record=evidence_index.record(loaded.accession),
        )
        _write_case(cases_dir / loaded.accession, result)
        all_solved.extend(result.solved)
        all_quarantine.extend(result.quarantine)
        all_hypotheses.extend(result.hypotheses)

    manifest_data: dict[str, Any] = {
        "run_id": resolved_run_id,
        "created_at": now.isoformat(),
        "total_filings": len(seeds),
        "total_solved_nodes": len(all_solved),
        "total_quarantined": len(all_quarantine),
        "total_hypotheses": len(all_hypotheses),
        "cases": [str(seed.accession) for seed in seeds],
        "solver_fingerprint": SOLVER_FINGERPRINT,
        "promoted_rules_loaded": promoted_loaded,
    }
    if gate_evidence is not None:
        manifest_data["gates"] = gate_evidence
    atomic_write_json(run_dir / "manifest.jsonl", manifest_data)

    return ReviewRun(
        run_id=resolved_run_id,
        run_dir=run_dir,
        total_filings=len(seeds),
        solved_count=len(all_solved),
        quarantine_count=len(all_quarantine),
        hypotheses_count=len(all_hypotheses),
    )


def promote_review_rule(
    rule_id: str,
    run_dir: Path,
    *,
    db_path: Path | None = None,
    evidence: dict[str, Any] | None = None,
) -> PromotedRuleRecord:
    """Promote a gate-evidenced hypothesis rule to the DuckDB knowledge base."""
    validate_gate_evidence(evidence)
    target_db = db_path or xbrl_paths().unification_rules_db_path
    target_db.parent.mkdir(parents=True, exist_ok=True)

    cases_dir = run_dir / "cases"
    matched_hyp: dict[str, Any] | None = None
    if cases_dir.is_dir():
        for case_p in cases_dir.iterdir():
            hyp_p = case_p / HYPOTHESES_FILE
            if hyp_p.is_file():
                for h in pq.read_table(hyp_p).to_pylist():
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
