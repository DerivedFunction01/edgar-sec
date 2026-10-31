"""Tests for XBRL review generation and gated rule promotion."""

from dataclasses import replace
from pathlib import Path
import random

import pyarrow as pa
import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.discovery.cohort import SeedFiling
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.counter_solver import (
    QUARANTINE_REASONS,
    AuditHypothesis,
    CounterSolver,
    CounterSolverOutcome,
    QuarantinedFact,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.infra.storage.parquet import write_parquet_table
from edgar_sec.pipelines.xbrl_review.bundles import (
    LoadedFiling,
    load_filing,
    registry_filings,
)
from edgar_sec.pipelines.xbrl_review.review import (
    _anchored_audit_targets,
    _audit_targets,
    _dimensional_audit_targets,
    _period_label,
    _quarantine_record,
    _representative_facts,
    build_engine_stack,
    execute_review_generation,
    promote_review_rule,
    solve_filing,
)
from edgar_sec.pipelines.xbrl_review.schemas import HYPOTHESES_SCHEMA

_ACCESSION = "0000063908-25-000012"
_PASSING_EVIDENCE = {
    "census": {"passed": True},
    "pair_gate": {"total": 18, "passed": 18},
    "battery": {
        "total": 188,
        "passed": 188,
        "failure_ids": [],
    },
}


def _seed() -> SeedFiling:
    return SeedFiling.from_dict(
        {
            "firm": "TST",
            "company_name": "Test Corp",
            "cik": "0000063908",
            "sic_code": 5812,
            "sector": "Testing",
            "fy": 2024,
            "form": "10-K",
            "accession": _ACCESSION,
            "sec_filing_url": "https://www.sec.gov/example",
        }
    )


def _fact(qname: str, value: float) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(_ACCESSION),
        concept_qname=qname,
        value=value,
        unit="USD",
        decimals=-6,
        period_type="instant",
        start_date=None,
        end_date=None,
        instant_date="2024-12-31",
        dimensions={},
        context_id="ctx",
    )


def _loaded(seed: SeedFiling) -> LoadedFiling:
    facts = (
        _fact("us-gaap:Assets", 100.0),
        _fact("us-gaap:CashAndCashEquivalentsAtCarryingValue", 60.0),
        _fact("us-gaap:AccountsReceivableNetCurrent", 40.0),
    )
    arcs = (
        CalculationArc(
            parent_qname="us-gaap:Assets",
            child_qname="us-gaap:CashAndCashEquivalentsAtCarryingValue",
            weight=1.0,
            order=1.0,
            role_uri="",
        ),
        CalculationArc(
            parent_qname="us-gaap:Assets",
            child_qname="us-gaap:AccountsReceivableNetCurrent",
            weight=1.0,
            order=2.0,
            role_uri="",
        ),
    )
    return LoadedFiling(
        seed=seed, bundle_dir=Path("."), facts=facts, calc_arcs=arcs, declarations={}
    )


def test_period_label_encodes_duration_span() -> None:
    """Verify duration labels carry start/end and instant labels stay single."""
    duration = XbrlFact(
        accession=AccessionNumber.from_any(_ACCESSION),
        concept_qname="us-gaap:NetIncomeLoss",
        value=1.0,
        period_type="duration",
        start_date="2023-01-01",
        end_date="2024-12-31",
        dimensions={},
    )
    assert _period_label(duration) == "2023-01-01/2024-12-31"
    assert _period_label(_fact("us-gaap:Assets", 1.0)) == "2024-12-31"


def test_solve_filing_partitions_bundle_facts() -> None:
    """Verify one filing solves into staged records with tokenized atoms."""
    seed = _seed()
    _taxonomy, solver, counter, tokenizer, _promoted = build_engine_stack((seed,))
    result = solve_filing(
        _loaded(seed), solver=solver, counter=counter, tokenizer=tokenizer
    )
    assert result.solved
    cash = next(
        r
        for r in result.solved
        if r.concept_qname == "us-gaap:CashAndCashEquivalentsAtCarryingValue"
    )
    assert cash.prime_head == "H_CASH"
    assert cash.reported_value == 60.0
    assert cash.derived_value is None
    assert len(result.rule_trace) == len(result.hypotheses)


def test_representative_facts_index_matches_scan_choice() -> None:
    """Verify the index keeps the first minimum under the scan's key."""
    dim_numeric = XbrlFact(
        accession=AccessionNumber.from_any(_ACCESSION),
        concept_qname="test:A",
        value=10.0,
        instant_date="2024-12-31",
        dimensions={"test:Axis": "test:M"},
    )
    undim_first = _fact("test:A", 20.0)
    undim_second = _fact("test:A", 5.0)
    dim_b = XbrlFact(
        accession=AccessionNumber.from_any(_ACCESSION),
        concept_qname="test:B",
        value=10.0,
        instant_date="2024-12-31",
        dimensions={"test:Axis": "test:M"},
    )
    undim_nonnumeric_b = XbrlFact(
        accession=AccessionNumber.from_any(_ACCESSION),
        concept_qname="test:B",
        value="n/a",
        instant_date="2024-12-31",
        dimensions={},
    )
    representatives = _representative_facts(
        (dim_numeric, undim_first, undim_second, dim_b, undim_nonnumeric_b)
    )
    assert representatives["test:A"] is undim_first
    assert representatives["test:B"] is undim_nonnumeric_b
    assert "test:Missing" not in representatives


class _CountingTokenizer:
    """Tokenizer wrapper recording every tokenize call's qname."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.qnames: list[str] = []

    def tokenize(self, qname: str, declaration=None, evidence=None):  # noqa: ANN001, ANN202
        """Record the qname and delegate to the wrapped tokenizer."""
        self.qnames.append(qname)
        return self._inner.tokenize(qname, declaration, evidence)  # type: ignore[attr-defined]


def test_solve_filing_tokenizes_once_per_distinct_qname() -> None:
    """Verify repeated predictions for one qname tokenize only once."""
    seed = _seed()
    loaded = _loaded(seed)
    cash = "us-gaap:CashAndCashEquivalentsAtCarryingValue"
    loaded = LoadedFiling(
        seed=seed,
        bundle_dir=Path("."),
        facts=loaded.facts + (_fact(cash, 61.0), _fact(cash, 62.0)),
        calc_arcs=loaded.calc_arcs,
        declarations={},
    )
    _taxonomy, solver, counter, tokenizer, _promoted = build_engine_stack((seed,))
    counting = _CountingTokenizer(tokenizer)
    result = solve_filing(
        loaded,
        solver=solver,
        counter=counter,
        tokenizer=counting,  # type: ignore[arg-type]
    )
    cash_records = [r for r in result.solved if r.concept_qname == cash]
    assert len(cash_records) == 3
    assert counting.qnames.count(cash) == 1
    assert sorted(counting.qnames) == sorted({r.concept_qname for r in result.solved})
    assert all(r.reported_value == 60.0 for r in cash_records)


class _RecordingCounter:
    """Counter stub capturing audit arguments and returning one hypothesis."""

    def __init__(self) -> None:
        self.declarations: object = None

    def audit_filing(self, **kwargs) -> CounterSolverOutcome:  # noqa: ANN003, ANN202
        """Record declarations and return a typed hypothesis outcome."""
        self.declarations = kwargs["declarations"]
        hypothesis = AuditHypothesis(
            concept_qname="us-gaap:OtherAssetsCurrent",
            hypothesized_parent="us-gaap:Assets",
            algebraic_weight=-1.0,
            hypothesis_type="RESIDUAL_COMPONENT",
            residual_delta=0.0,
            period="2024-12-31",
        )
        return CounterSolverOutcome((), (), (), (hypothesis,))


def test_solve_filing_threads_declarations_and_period() -> None:
    """Verify declarations reach the audit and period reaches the record."""
    seed = _seed()
    loaded = _loaded(seed)
    declarations = {
        "us-gaap:Assets": ConceptDeclaration(
            "us-gaap:Assets", "Assets", item_type="xbrli:monetaryItemType"
        )
    }
    loaded = LoadedFiling(
        seed=seed,
        bundle_dir=Path("."),
        facts=loaded.facts,
        calc_arcs=loaded.calc_arcs,
        declarations=declarations,
    )
    _taxonomy, solver, _counter, tokenizer, _promoted = build_engine_stack((seed,))
    counter = _RecordingCounter()
    result = solve_filing(
        loaded,
        solver=solver,
        counter=counter,
        tokenizer=tokenizer,  # type: ignore[arg-type]
    )
    assert counter.declarations is declarations
    assert len(result.hypotheses) == 1
    hypothesis = result.hypotheses[0]
    assert hypothesis.hypothesis_type == "RESIDUAL_COMPONENT"
    assert hypothesis.period == "2024-12-31"
    assert hypothesis.rule_id.startswith("HYP_RESIDUAL_")


def _dim_fact(
    qname: str, value: float, instant: str, dimensions: dict[str, str]
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(_ACCESSION),
        concept_qname=qname,
        value=value,
        unit="USD",
        decimals=-6,
        period_type="instant",
        instant_date=instant,
        dimensions=dimensions,
    )


def test_solve_filing_audits_dimensioned_only_parent_per_context() -> None:
    """Verify balanced contexts are consumed and partial ones quarantined."""
    seed = _seed()
    dims = {"test:PlanAxis": "test:PensionMember"}
    parent = "test:PlanAmountsRecognized"
    assets = "test:PlanAssets"
    obligation = "test:PlanObligation"
    # decimals=0 keeps the 130-vs-999 slice imbalance outside filed precision.
    facts = tuple(
        replace(fact, decimals=0)
        for fact in (
            _dim_fact(parent, 100.0, "2024-12-31", dims),
            _dim_fact(assets, 130.0, "2024-12-31", dims),
            _dim_fact(obligation, 30.0, "2024-12-31", dims),
            _dim_fact(parent, 50.0, "2023-12-31", dims),
            _dim_fact(assets, 50.0, "2023-12-31", dims),
            _fact(assets, 999.0),
        )
    )
    arcs = (
        CalculationArc(parent, assets, weight=1.0),
        CalculationArc(parent, obligation, weight=-1.0),
    )
    loaded = LoadedFiling(
        seed=seed, bundle_dir=Path("."), facts=facts, calc_arcs=arcs, declarations={}
    )
    assert _audit_targets(loaded) == []
    assert _dimensional_audit_targets(loaded) == [parent]

    _taxonomy, solver, counter, tokenizer, _promoted = build_engine_stack((seed,))
    result = solve_filing(loaded, solver=solver, counter=counter, tokenizer=tokenizer)
    quarantined = {(r.concept_qname, r.period) for r in result.quarantine}
    assert quarantined == {
        (parent, "2023-12-31"),
        (assets, "2024-12-31"),
    }
    by_concept = {r.concept_qname: r for r in result.quarantine}
    assert by_concept[parent].fact_count == 1
    assert by_concept[parent].reason == (
        "DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED"
    )
    assert by_concept[assets].fact_count == 2
    assert by_concept[assets].numeric_value == 999.0
    assert by_concept[assets].reason == "UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED"


def test_solve_filing_audits_anchored_parent_dimensioned_context() -> None:
    """Verify a mixed parent's balanced dimensioned context is consumed."""
    seed = _seed()
    dims = {"test:PlanAxis": "test:PensionMember"}
    parent = "test:PlanAmountsRecognized"
    assets = "test:PlanAssets"
    obligation = "test:PlanObligation"
    facts = (
        _fact(parent, 100.0),
        _fact(assets, 130.0),
        _dim_fact(parent, 70.0, "2024-12-31", dims),
        _dim_fact(assets, 100.0, "2024-12-31", dims),
        _dim_fact(obligation, 30.0, "2024-12-31", dims),
        _dim_fact(obligation, 30.0, "2023-12-31", dims),
    )
    arcs = (
        CalculationArc(parent, assets, weight=1.0),
        CalculationArc(parent, obligation, weight=-1.0),
    )
    loaded = LoadedFiling(
        seed=seed, bundle_dir=Path("."), facts=facts, calc_arcs=arcs, declarations={}
    )
    assert _audit_targets(loaded) == [parent]
    assert _dimensional_audit_targets(loaded) == []
    assert _anchored_audit_targets(loaded) == [parent, assets]

    _taxonomy, solver, counter, tokenizer, _promoted = build_engine_stack((seed,))
    result = solve_filing(loaded, solver=solver, counter=counter, tokenizer=tokenizer)
    quarantined = {(r.concept_qname, r.period) for r in result.quarantine}
    assert quarantined == {(obligation, "2023-12-31")}


def test_solve_filing_quarantine_pairs_carry_reason_and_fact_count() -> None:
    """Verify staged pairs carry the pair reason and unconsumed count."""
    seed = _seed()
    orphan = "test:OrphanMetric"
    loaded = _loaded(seed)
    facts = loaded.facts + (
        _dim_fact(orphan, 9.0, "2024-12-31", {}),
        _dim_fact(orphan, 7.0, "2023-12-31", {}),
        _dim_fact(orphan, 5.0, "2024-12-31", {}),
    )
    loaded = LoadedFiling(
        seed=seed,
        bundle_dir=Path("."),
        facts=facts,
        calc_arcs=loaded.calc_arcs,
        declarations={},
    )
    _taxonomy, solver, counter, tokenizer, _promoted = build_engine_stack((seed,))
    result = solve_filing(loaded, solver=solver, counter=counter, tokenizer=tokenizer)
    assert all(record.reason in QUARANTINE_REASONS for record in result.quarantine)
    matches = [r for r in result.quarantine if r.concept_qname == orphan]
    assert len(matches) == 1
    record = matches[0]
    assert record.reason == "UNDIMENSIONED_NO_CALC_ROLE"
    assert record.fact_count == 3
    assert record.period == "2023-12-31"
    assert record.numeric_value == 7.0


def _quarantined_member(
    qname: str, value: float, instant: str, dimensions: dict[str, str]
) -> QuarantinedFact:
    return QuarantinedFact(
        fact=_dim_fact(qname, value, instant, dimensions),
        reason="UNDIMENSIONED_NO_CALC_ROLE",
    )


def test_quarantine_representative_is_input_order_invariant() -> None:
    """Verify shuffled members collapse to the same representative record."""
    qname = "test:OrphanMetric"
    members = [
        _quarantined_member(qname, 1.0, "2022-12-31", {"test:Axis": "test:M"}),
        _quarantined_member(qname, 50.0, "2024-12-31", {}),
        _quarantined_member(qname, 30.0, "2024-12-31", {}),
        _quarantined_member(qname, 20.0, "2023-12-31", {}),
    ]
    expected = _quarantine_record(_ACCESSION, "TST", members)
    assert expected.period == "2023-12-31"
    assert expected.numeric_value == 20.0
    assert expected.fact_count == 4
    rng = random.Random(20261027)
    for _ in range(8):
        shuffled = list(members)
        rng.shuffle(shuffled)
        assert _quarantine_record(_ACCESSION, "TST", shuffled) == expected


def test_real_filing_quarantine_rows_carry_vocabulary_reasons() -> None:
    """Verify a real bundle's staged rows use only vocabulary reasons."""
    seed = registry_filings((_ACCESSION,))[0]
    loaded = load_filing(seed)
    _taxonomy, solver, counter, tokenizer, _promoted = build_engine_stack((seed,))
    result = solve_filing(loaded, solver=solver, counter=counter, tokenizer=tokenizer)
    outcome = counter.audit_filing(
        facts=loaded.facts,
        target_goals=_audit_targets(loaded),
        calculation_arcs=loaded.calc_arcs,
        dimensional_target_goals=_dimensional_audit_targets(loaded),
        anchored_target_goals=_anchored_audit_targets(loaded),
        declarations=loaded.declarations,
    )
    assert result.quarantine
    assert all(record.reason in QUARANTINE_REASONS for record in result.quarantine)
    assert all(record.fact_count >= 1 for record in result.quarantine)
    assert sum(r.fact_count for r in result.quarantine) == len(
        outcome.quarantined_facts
    )
    assert len(result.quarantine) == len(
        {q.fact.concept_qname for q in outcome.quarantined_facts}
    )


def test_bac_parent_is_a_dimensional_target_only() -> None:
    """Verify the BAC 2024 specimen parent joins only the dimensional set."""
    loaded = load_filing(registry_filings(("0000070858-25-000139",))[0])
    parent = "us-gaap:DefinedBenefitPlanAmountsRecognizedInBalanceSheet"
    assert parent in _dimensional_audit_targets(loaded)
    assert parent not in _audit_targets(loaded)


def test_generation_refuses_filings_without_bundles(tmp_path: Path) -> None:
    """Verify generation fails loudly when a filing has no seed bundle."""
    row = {
        "firm": "ZZZ",
        "company_name": "Missing Bundle Corp",
        "cik": "0000000000",
        "sic_code": 9999,
        "sector": "Testing",
        "fy": 2024,
        "form": "10-K",
        "accession": "0000000000-25-000001",
        "sec_filing_url": "https://www.sec.gov/example",
    }
    with pytest.raises(ValueError, match="0000000000-25-000001"):
        execute_review_generation([row], run_id="run-test", output_root=tmp_path)


def _run_dir_with_hypothesis(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run-hyp"
    case_dir = run_dir / "cases" / _ACCESSION
    case_dir.mkdir(parents=True)
    table = pa.Table.from_pylist(
        [
            {
                "rule_id": "HYP_TEST_1",
                "hypothesis_type": "RESIDUAL_COMPONENT",
                "target_concept": "us-gaap:Assets",
                "source_concept": "us-gaap:OtherAssetsCurrent",
                "algebraic_weight": 1.0,
                "firm": "TST",
                "sector": "Testing",
                "evidence_value": 5.0,
            }
        ],
        schema=HYPOTHESES_SCHEMA,
    )
    write_parquet_table(table, case_dir / "hypotheses.parquet")
    return run_dir


def test_promote_refuses_without_gate_evidence(tmp_path: Path) -> None:
    """Verify promotion refuses when gate evidence is absent."""
    run_dir = _run_dir_with_hypothesis(tmp_path)
    with pytest.raises(ValueError, match="gate evidence"):
        promote_review_rule("HYP_TEST_1", run_dir, db_path=tmp_path / "kb.duckdb")


def test_promote_refuses_with_failing_evidence(tmp_path: Path) -> None:
    """Verify promotion refuses when a gate is failing."""
    run_dir = _run_dir_with_hypothesis(tmp_path)
    evidence = {**_PASSING_EVIDENCE, "census": {"passed": False}}
    with pytest.raises(ValueError, match="census"):
        promote_review_rule(
            "HYP_TEST_1", run_dir, db_path=tmp_path / "kb.duckdb", evidence=evidence
        )


def test_promote_writes_rule_and_kb_loads_it_back(tmp_path: Path) -> None:
    """Verify a promoted rule lands in DuckDB and loads into a fresh KB."""
    run_dir = _run_dir_with_hypothesis(tmp_path)
    db_path = tmp_path / "kb.duckdb"
    record = promote_review_rule(
        "HYP_TEST_1", run_dir, db_path=db_path, evidence=_PASSING_EVIDENCE
    )
    assert record.target_concept == "us-gaap:Assets"

    kb = EvidenceKnowledgeBase(taxonomy=load_domain_taxonomy())
    assert kb.load_promoted_rules(db_path) == 1
    assert kb.load_promoted_rules(db_path) == 0
    rule = next(r for r in kb.rules if r.rule_id == "HYP_TEST_1")
    assert rule.target_node == "us-gaap:Assets"
    assert rule.concept_qname == "us-gaap:OtherAssetsCurrent"
    assert rule.scope == ("TST", "Testing", "*")
    weight = CounterSolver.evaluate_rule_weight(rule, "TST", "Testing")
    assert weight == 1.0
