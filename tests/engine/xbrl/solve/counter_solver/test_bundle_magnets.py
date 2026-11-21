"""Seed-bundle magnet specimens: rate and EPS parents emit nothing."""

from edgar_sec.engine.xbrl.solve.counter_solver import CounterSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
)
from tests.engine.xbrl.solve.counter_solver.conftest import _StubPrimarySolver
from tests.support.corpus import bundle_dir


def _seed_declarations(folder: str) -> dict[str, ConceptDeclaration]:
    import pyarrow.parquet as pq

    rows = pq.read_table(bundle_dir(folder) / "declarations.parquet").to_pylist()
    return {
        row["concept_qname"]: ConceptDeclaration(
            concept_qname=row["concept_qname"],
            name=row["name"],
            period_type=row["period_type"],
            balance=row["balance"],
            substitution_group=row["substitution_group"],
            item_type=row["item_type"],
        )
        for row in rows
    }


def _bundle_outcome(folder: str):  # noqa: ANN202
    """Audit one seed bundle through the stub solver and real taxonomy."""
    facts = load_seed_facts(folder)
    arcs = load_seed_calculation_arcs(folder)
    reported = {
        fact.concept_qname
        for fact in facts
        if not fact.dimensions and isinstance(fact.value, (int, float))
    }
    goals = sorted({arc.parent_qname for arc in arcs if arc.parent_qname in reported})
    kb = EvidenceKnowledgeBase(load_domain_taxonomy())
    counter = CounterSolver(_StubPrimarySolver(kb))  # type: ignore[arg-type]
    return counter.audit_filing(
        facts,
        target_goals=goals,
        calculation_arcs=arcs,
        declarations=_seed_declarations(folder),
    )


def test_apd_bundle_eps_and_tax_rate_magnets_emit_nothing() -> None:
    """Verify the APD bundle's rate/EPS magnets produce no hypotheses."""
    outcome = _bundle_outcome("apd_2024_10k")
    targets = {h.hypothesized_parent for h in outcome.hypotheses}
    assert "us-gaap:EarningsPerShareBasic" not in targets
    assert not any("EffectiveIncomeTaxRate" in target for target in targets)
    assert all(
        h.hypothesis_type == "RESIDUAL_COMPONENT" and h.period
        for h in outcome.hypotheses
    )


def test_bac_2011_bundle_tax_recon_magnet_emits_nothing() -> None:
    """Verify the BAC 2011 tax-reconciliation magnet produces no hypotheses."""
    outcome = _bundle_outcome("bac_2011_10k")
    targets = {h.hypothesized_parent for h in outcome.hypotheses}
    assert "us-gaap:EffectiveIncomeTaxRateReconciliationTaxContingencies" not in targets
    assert not any("EffectiveIncomeTaxRate" in target for target in targets)
