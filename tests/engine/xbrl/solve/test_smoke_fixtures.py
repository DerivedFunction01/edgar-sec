"""Direct-fact smoke cases grounded in each bundled filing."""

import json

from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.verification import DoubleCountVerifier
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support import fixture_path
from .conftest import load_seed_facts


def test_seed_instant_balance_sheet_smoke_cases() -> None:
    manifest = json.loads(
        fixture_path("xbrl/seed/solver_smoke_cases.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        fixture_path("xbrl/seed/fixture_source_registry.json").read_text(
            encoding="utf-8"
        )
    )
    sources = {item["folder"]: item for item in registry["bundles"]}
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=load_domain_taxonomy()))
    )

    assert {case["folder"] for case in manifest["cases"]} == set(sources)
    for case in manifest["cases"]:
        source = sources[case["folder"]]
        assert case["firm"] == source["firm"]
        assert case["source_accession"] == source["source_accession"]

        facts = load_seed_facts(case["folder"])
        scope = FactScope(
            accession=case["source_accession"],
            instant_date=case["instant_date"],
            unit=case["unit"],
            dimensions=case["dimensions"],
        )
        matching = tuple(
            fact for fact in scope.select(facts) if fact.concept_qname == case["qname"]
        )
        contexts = {
            (
                str(fact.accession),
                fact.concept_qname,
                fact.period_type,
                fact.instant_date,
                fact.unit,
                tuple(sorted(fact.dimensions.items())),
                fact.context_id,
                fact.value,
            )
            for fact in matching
        }
        assert len(contexts) == 1, (case["folder"], contexts)
        assert matching[0].period_type == case["period_type"]
        assert matching[0].context_id == case["context_id"]
        assert matching[0].value == case["value"]

        result = engine.execute(FinancialQuery(case["term"], scope), facts)
        assert result.status == QueryStatus.REPORTED, (case["folder"], result)
        assert result.candidate_qnames == (case["qname"],)
        assert result.reported_fact is not None
        assert result.reported_fact == matching[0]
        assert result.value == case["value"]

        rendered_text = fixture_path(
            f"xbrl/seed/{case['folder']}/normalized_text.txt"
        ).read_text(encoding="utf-8")
        lines = rendered_text.splitlines()
        assert lines[case["line_number"] - 1].strip() == case["rendered_row"]
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
        assert evidence.is_valid, (case["folder"], evidence.message)
        assert evidence.printed_value * case["scale"] == case["value"]
        assert evidence.citation == (
            f"line {case['line_number']}: {case['rendered_row']}"
        )
