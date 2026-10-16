"""Cited identity, debt, AOCI, and derivative fixture equations."""

import json

from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.solve.identities import verify_balance_sheet_identity
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.solve.verification import DoubleCountVerifier
from tests.support import fixture_path
from .conftest import load_seed_facts


def _load_manifest() -> dict:
    return json.loads(
        fixture_path("xbrl/seed/solver_smoke_cases.json").read_text(encoding="utf-8")
    )


def _engine() -> FinancialQueryEngine:
    solver = XbrlConstraintSolver(
        EvidenceKnowledgeBase(taxonomy=load_domain_taxonomy())
    )
    return FinancialQueryEngine(solver)


def _assert_reported_case(
    case: dict,
    facts: list,
    engine: FinancialQueryEngine,
    accession: str,
    unit: str,
    dimensions: dict,
    period: dict,
    rendered_text: str,
) -> float:
    scope = FactScope(
        accession=accession,
        unit=unit,
        dimensions=dimensions,
        **period,
    )
    result = engine.execute(FinancialQuery(case["term"], scope), facts)
    assert result.status == QueryStatus.REPORTED, result
    assert result.candidate_qnames == (case["qname"],)
    assert result.reported_fact is not None
    assert result.reported_fact.value == case["value"]
    assert result.value == case["value"]
    assert result.reported_fact.context_id == case["context_id"]

    evidence = DoubleCountVerifier.verify_cited_row(
        rendered_text,
        case["label"],
        case["value"],
        line_number=case["line_number"],
        line_range=tuple(case["line_range"]),
        scale=case["scale"],
        column_index=case["column_index"],
        expected_snippet=case["rendered_row"],
    )
    assert evidence.is_valid, evidence.message
    assert evidence.printed_value is not None
    return evidence.printed_value * case["scale"]


def test_msft_scoped_balance_sheet_identity_has_cited_facts() -> None:
    case = _load_manifest()["accounting_identity"]
    facts = load_seed_facts(case["folder"])
    text = fixture_path(f"xbrl/seed/{case['folder']}/normalized_text.txt").read_text(
        encoding="utf-8"
    )
    engine = _engine()
    values = [
        _assert_reported_case(
            item,
            facts,
            engine,
            case["source_accession"],
            case["unit"],
            case["dimensions"],
            {"instant_date": case["instant_date"]},
            text,
        )
        for item in case["facts"]
    ]

    scope = FactScope(
        accession=case["source_accession"],
        instant_date=case["instant_date"],
        unit=case["unit"],
        dimensions=case["dimensions"],
    )
    identity = verify_balance_sheet_identity(facts, scope=scope)

    assert values[0] == values[1] + values[2] == case["equation_value"]
    assert identity is not None
    assert identity.passed
    assert identity.lhs_value == identity.rhs_value == case["equation_value"]


def test_msft_debt_carrying_fair_value_and_maturities_stay_distinct() -> None:
    case = _load_manifest()["debt_distinction"]
    facts = load_seed_facts(case["folder"])
    text = fixture_path(f"xbrl/seed/{case['folder']}/normalized_text.txt").read_text(
        encoding="utf-8"
    )
    engine = _engine()
    carrying_values = [
        _assert_reported_case(
            item,
            facts,
            engine,
            case["source_accession"],
            case["unit"],
            case["dimensions"],
            {"instant_date": case["instant_date"]},
            text,
        )
        for item in case["carrying_facts"]
    ]
    fair_value = case["fair_value"]
    fair_evidence = DoubleCountVerifier.verify_cited_row(
        text,
        fair_value["label"],
        fair_value["value"],
        line_number=fair_value["line_number"],
        line_range=tuple(fair_value["line_range"]),
        scale=fair_value["scale"],
        column_index=fair_value["column_index"],
        expected_snippet=fair_value["rendered_row"],
    )
    maturities = case["principal_maturities"]
    maturity_evidence = DoubleCountVerifier.verify_cited_row(
        text,
        maturities["label"],
        maturities["value"],
        line_number=maturities["line_number"],
        line_range=tuple(maturities["line_range"]),
        scale=maturities["scale"],
        column_index=maturities["column_index"],
        expected_snippet=maturities["rendered_row"],
    )

    carrying_total = sum(carrying_values)
    assert carrying_total == 44937000000.0
    assert fair_evidence.is_valid, fair_evidence.message
    assert maturity_evidence.is_valid, maturity_evidence.message
    assert fair_value["value"] != carrying_total
    assert maturities["value"] != carrying_total
    assert fair_value["value"] != maturities["value"]


def test_aapl_aoci_opening_change_and_ending_use_exact_contexts() -> None:
    case = _load_manifest()["aoci_rollforward"]
    facts = load_seed_facts(case["folder"])
    text = fixture_path(f"xbrl/seed/{case['folder']}/normalized_text.txt").read_text(
        encoding="utf-8"
    )
    engine = _engine()
    values = []
    for name in ("opening", "change", "ending"):
        item = case[name]
        values.append(
            _assert_reported_case(
                item,
                facts,
                engine,
                case["source_accession"],
                case["unit"],
                case["dimensions"],
                item["scope"],
                text,
            )
        )

    assert values[0] + values[1] == values[2]


def test_jpm_derivative_netting_equation_uses_comparative_column() -> None:
    case = _load_manifest()["jpm_derivative_netting"]
    facts = load_seed_facts(case["folder"])
    text = fixture_path(f"xbrl/seed/{case['folder']}/normalized_text.txt").read_text(
        encoding="utf-8"
    )
    recognized = _assert_reported_case(
        case["recognized"],
        facts,
        _engine(),
        case["source_accession"],
        case["unit"],
        case["dimensions"],
        {"instant_date": case["instant_date"]},
        text,
    )
    rendered_values = []
    for name in ("collateral_not_nettable", "net_amount"):
        row = case[name]
        evidence = DoubleCountVerifier.verify_cited_row(
            text,
            row["label"],
            row["value"],
            line_number=row["line_number"],
            line_range=tuple(row["line_range"]),
            scale=row["scale"],
            column_index=row["column_index"],
            expected_snippet=row["rendered_row"],
        )
        assert evidence.is_valid, evidence.message
        assert evidence.printed_value is not None
        rendered_values.append(evidence.printed_value * row["scale"])

    assert recognized + rendered_values[0] == rendered_values[1]
