"""Seeded pair and battery gate entry points for the XBRL census."""

from __future__ import annotations

from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def run_pair_gate() -> object:
    """Evaluate the seeded pair set and longitudinal relations, grounded."""
    from edgar_sec.engine.xbrl.review.benchmark_pairs import (
        PAIR_SET,
        PairReport,
        evaluate_pairs,
    )
    from edgar_sec.engine.xbrl.review.relations import (
        RELATION_SET,
        evaluate_relations,
    )
    from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
    from edgar_sec.engine.xbrl.solve.cohort.cohort_lookup import CohortLookup
    from edgar_sec.engine.xbrl.solve.concepts.concept_table import build_cohort_table
    from edgar_sec.engine.xbrl.solve.core.query import FinancialQueryEngine
    from edgar_sec.engine.xbrl.solve.core.solver import XbrlConstraintSolver
    from edgar_sec.tools.xbrl_eval.xbrl_census_corpus import (
        latest_scoped_fact,
        latest_undimensioned_fact,
        load_seed_arcs,
        load_seed_facts,
        corpus_cohort_entries,
    )

    taxonomy = load_domain_taxonomy()
    entries = corpus_cohort_entries()
    lookup = CohortLookup(build_cohort_table(taxonomy, entries), entries)
    try:
        source_facts = {}
        for spec in PAIR_SET:
            if not spec.source_firm:
                continue
            folder = f"{spec.source_firm.lower()}_2024_10k"
            if spec.source_scope:
                source_facts[(spec.source_firm, spec.target)] = latest_scoped_fact(
                    folder, spec.target, dict(spec.source_scope)
                )
            else:
                source_facts[(spec.source_firm, spec.target)] = (
                    latest_undimensioned_fact(folder, spec.target)
                )
        pairs = evaluate_pairs(lookup, PAIR_SET, source_facts)
    finally:
        lookup.close()
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=taxonomy))
    )
    folder_by_accession = {
        str(entry.accession): entry.facts_path.parent.name for entry in entries
    }
    endpoints = {}
    for spec in RELATION_SET:
        for accession in (spec.pre_accession, spec.post_accession):
            folder = folder_by_accession[accession]
            endpoints[accession] = (load_seed_facts(folder), load_seed_arcs(folder))
    relations = evaluate_relations(engine, endpoints)
    return PairReport(
        total=pairs.total + relations.total,
        passed=pairs.passed + relations.passed,
        failures=pairs.failures + relations.failures,
    )


def run_battery_gate() -> object:
    """Evaluate the answerability battery against the seed bundles."""
    from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
    from edgar_sec.engine.xbrl.review.battery import BATTERY_SET, evaluate_battery
    from edgar_sec.engine.xbrl.solve.core.query import FinancialQueryEngine
    from edgar_sec.engine.xbrl.solve.core.solver import XbrlConstraintSolver
    from edgar_sec.tools.xbrl_eval.xbrl_census_corpus import (
        load_seed_arcs,
        load_seed_facts,
        corpus_cohort_entries,
    )

    taxonomy = load_domain_taxonomy()
    entries = corpus_cohort_entries()
    folder_by_accession = {
        str(entry.accession): entry.facts_path.parent.name for entry in entries
    }
    endpoints = {}
    for entry in BATTERY_SET:
        if entry.accession not in endpoints:
            folder = folder_by_accession[entry.accession]
            endpoints[entry.accession] = (
                load_seed_facts(folder),
                load_seed_arcs(folder),
            )
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=taxonomy))
    )
    return evaluate_battery(engine, endpoints)
