"""Shared verification helpers for the grounded seed fixture suites."""

from __future__ import annotations

import json

import pyarrow.parquet as pq

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
from tests.support.corpus import (
    bundle_dir,
    bundle_text,
    corpus_cohort_rows,
    corpus_source_bundles,
)

from .conftest import load_seed_calculation_arcs, load_seed_facts


def _verify_fixture(
    firm_folder: str, expected_firm: str, expected_accession: str
) -> None:
    fixture_dir = bundle_dir(firm_folder)
    source = next(
        item for item in corpus_source_bundles() if item["folder"] == firm_folder
    )
    trace_file = fixture_dir / "verification_trace.json"
    assert trace_file.is_file()

    trace = json.loads(trace_file.read_text(encoding="utf-8"))
    assert trace["firm"] == expected_firm
    assert trace["accession"] == expected_accession
    assert trace["accession"] == source["source_accession"]
    assert trace["fiscal_year"] == source["reported_fiscal_year"]
    assert trace["source_filing_fiscal_year"] == source["source_filing_fiscal_year"]

    cohort_entry = next(
        item
        for item in corpus_cohort_rows()
        if item["accession"] == source["cohort_accession"]
    )
    assert cohort_entry["firm"] == expected_firm
    assert cohort_entry["accession"] == source["cohort_accession"]
    assert cohort_entry["fy"] == source["cohort_fiscal_year"]
    assert source["source_matches_cohort"] is (
        source["source_accession"] == source["cohort_accession"]
    )

    rendered_text = bundle_text(firm_folder)
    lines = rendered_text.splitlines()
    assert str(source["source_filing_fiscal_year"]) in "\n".join(lines[:40])

    raw_facts = pq.read_table(fixture_dir / "facts.parquet").to_pylist()
    assert len(raw_facts) > 1000
    assert {row["accession"] for row in raw_facts} == {source["source_accession"]}
    assert all(row["accession"] == trace["accession"] for row in raw_facts)
    assert source["source_cik_matches_registrant"] is (
        trace["cik"].lstrip("0") == cohort_entry["cik"].lstrip("0")
    )
    arcs = load_seed_calculation_arcs(firm_folder)
    assert len(arcs) > 100

    assert source["provenance_status"] in (
        "VERIFIED",
        "VERIFIED_COMPARATIVE_PERIOD",
    )

    facts = load_seed_facts(firm_folder)
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=load_domain_taxonomy()))
    )

    stmt = trace["statement_of_operations"]
    scale = stmt["scale"]
    unit = stmt["unit"].split()[0]
    column_index = stmt.get("period_column_index", 0)
    line_range = tuple(stmt["line_range"])
    for concept in stmt["concepts"]:
        line_idx = concept["line_number"] - 1
        assert 0 <= line_idx < len(lines)
        actual_line = lines[line_idx].strip()
        assert actual_line == concept["snippet"]
        display_sign = concept.get("display_sign", 1)
        assert (
            abs(
                concept["table_value"] * scale * display_sign
                - concept["reported_value"]
            )
            < 1.0
        )

        rendered = DoubleCountVerifier.verify_cited_row(
            rendered_text,
            concept["label"],
            concept["reported_value"],
            line_number=concept["line_number"],
            line_range=line_range,
            scale=scale,
            column_index=column_index,
            expected_snippet=concept["snippet"],
            display_sign=display_sign,
        )
        assert rendered.is_valid, rendered.message
        assert rendered.citation.startswith(f"line {concept['line_number']}:")

        qname = concept["concept_qname"]
        dimensions = concept.get("dimensions", {})
        matching_facts = [
            row
            for row in raw_facts
            if row["concept_qname"] == qname
            and row["numeric_value"] == concept["reported_value"]
            and row["unit"] == unit
            and json.loads(row["dimensions_json"]) == dimensions
            and row["period_type"] == "duration"
            and row["end_date"][:4] == str(source["reported_fiscal_year"])
        ]
        contexts = {
            (
                row["start_date"],
                row["end_date"],
                row["unit"],
                row["dimensions_json"],
            )
            for row in matching_facts
        }
        assert len(contexts) == 1, (firm_folder, qname, contexts)
        matching = matching_facts[0]
        scope = FactScope(
            accession=source["source_accession"],
            start_date=matching["start_date"],
            end_date=matching["end_date"],
            unit=unit,
            dimensions=dimensions,
        )
        queried = engine.execute(FinancialQuery(qname, scope), facts, arcs)
        assert queried.status == QueryStatus.REPORTED, (firm_folder, qname, queried)
        assert queried.value == concept["reported_value"]

    proof = stmt["anti_chain_proof"]
    calc_sum = sum(c["weight"] * c["value"] for c in proof["components"])
    assert calc_sum == proof["target_value"]
    assert proof["is_valid_antichain"] is True
    for component in proof["components"]:
        assert any(
            row["concept_qname"] == component["concept"]
            and row["numeric_value"] == component["value"]
            and not json.loads(row["dimensions_json"])
            and row["end_date"][:4] == str(source["reported_fiscal_year"])
            for row in raw_facts
        )


def _grounded_engine() -> FinancialQueryEngine:
    return FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=load_domain_taxonomy()))
    )


def _bac_query(qname: str, accession: str, instant: str, folder: str, **kwargs):
    return _grounded_engine().execute(
        FinancialQuery(
            qname,
            FactScope(accession=accession, instant_date=instant, unit="USD"),
            **kwargs,
        ),
        load_seed_facts(folder),
        load_seed_calculation_arcs(folder),
    )


_BAC_CASH_2011 = "us-gaap:CashAndCashEquivalentsAtCarryingValue"


_BAC_CASH_2024 = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"


_BAC_ACC_2011 = "0000070858-12-000155"


_BAC_ACC_2024 = "0000070858-25-000139"
