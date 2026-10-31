"""Tests pinning composed-chain semantics: status, veto, compatibility."""

from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.apps.client.comparison import compare_compositions
from edgar_sec.apps.client.composition import (
    STATUS_ORDER,
    evaluate_chain,
    resolve_operand,
)
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.review.chains import CHAIN_SET, ChainSpec
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    FilingXbrl,
    LinkbaseBundle,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.concept_table import (
    CohortEntry,
    ConceptTable,
    build_cohort_table,
    build_concept_table,
)
from edgar_sec.engine.xbrl.solve.equivalence import (
    UNRELATED,
    RankedEquivalent,
    classify_ladder_pair,
    classify_pair,
)
from edgar_sec.engine.xbrl.solve.evidence_index import (
    ConceptEvidence,
    FilingEvidenceRecord,
    build_evidence_index,
    build_filing_evidence,
)
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryResult,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.storage.storage import write_facts_parquet
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_cohort,
    load_seed_facts,
)

_FCF_TERMS = (
    ("+", "cfo"),
    ("-", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"),
)


def _create_xbrl_facade(firm: str) -> Xbrl:
    facts = load_seed_facts(f"{firm}_2024_10k")
    arcs = load_seed_calculation_arcs(f"{firm}_2024_10k")
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def test_compose_free_cash_flow_worked_preset() -> None:
    """Verify the FCF chain composes cfo - capex through query resolution."""
    msft = _create_xbrl_facade("msft")
    result = msft.compose(_FCF_TERMS, fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 74_071_000_000.0
    assert msft.financials.free_cash_flow == result.value


def test_compose_unit_mismatch_is_conflict_naming_operand() -> None:
    """Verify a shares-denominated operand conflicts with a USD operand."""
    msft = _create_xbrl_facade("msft")
    result = msft.compose(
        (
            ("+", "cfo"),
            ("-", "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding"),
        ),
        fiscal_year=2024,
    )
    assert result.status == QueryStatus.CONFLICT
    assert result.value is None
    assert "WeightedAverageNumberOfDilutedSharesOutstanding" in result.message


def test_compose_unavailable_operand_carries_no_value() -> None:
    """Verify one UNAVAILABLE operand poisons the chain's value."""
    msft = _create_xbrl_facade("msft")
    result = msft.compose(
        (("+", "revenue"), ("-", "UnrecognizedFinancialMeasure")),
        fiscal_year=2024,
    )
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_compose_antichain_veto_on_ancestor_operand() -> None:
    """Verify composing a total with its own child is vetoed as double-counting."""
    msft = _create_xbrl_facade("msft")
    result = msft.compose(
        (("+", "us-gaap:Assets"), ("-", "us-gaap:AssetsCurrent")),
        fiscal_year=2024,
    )
    assert result.status == QueryStatus.CONFLICT
    assert result.value is None
    assert "Double-counting" in result.message


def test_compose_operands_carry_name_provenance() -> None:
    """Verify name-resolved operands expose the name rung, at REPORTED."""
    msft = _create_xbrl_facade("msft")
    result = msft.compose(_FCF_TERMS, fiscal_year=2024)
    assert [op.provenance for op in result.operands] == ["name", "name"]
    assert [op.status for op in result.operands] == [
        QueryStatus.REPORTED,
        QueryStatus.REPORTED,
    ]


def test_compose_default_mediated_operand_carries_default_provenance() -> None:
    """Verify a bare-payables operand resolved via the global default says so."""
    fact = XbrlFact(
        accession=AccessionNumber("0000000000-24-000000"),
        concept_qname="us-gaap:AccountsPayable",
        value=100.0,
        unit="USD",
        period_type="instant",
        instant_date="2024-12-31",
    )
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=(fact,),
        linkbases=LinkbaseBundle(calculation_arcs=()),
    )
    facade = Xbrl(bundle, load_domain_taxonomy())
    result = facade.compose((("+", "AccruedLiabilitiesCurrent"),))
    assert result.status == QueryStatus.REPORTED
    assert result.value == 100.0
    (operand,) = result.operands
    assert operand.concept_qname == "us-gaap:AccountsPayable"
    assert operand.provenance == "default"
    assert operand.unit == "USD"
    assert operand.period_key == "instant:2024-12-31"


def _query_result(
    provenance: str = "",
    equivalents: tuple[RankedEquivalent, ...] = (),
) -> FinancialQueryResult:
    """One reported bare-payables result, with optional rung markers."""
    fact = XbrlFact(
        accession=AccessionNumber("0000000000-24-000000"),
        concept_qname="us-gaap:AccountsPayable",
        value=100.0,
        unit="USD",
        period_type="instant",
        instant_date="2024-12-31",
    )
    return FinancialQueryResult(
        query=FinancialQuery(
            term="AccruedLiabilitiesCurrent",
            scope=FactScope(accession="0000000000-24-000000"),
        ),
        status=QueryStatus.REPORTED,
        candidate_qnames=(fact.concept_qname,),
        reported_fact=fact,
        equivalents=equivalents,
        provenance=provenance,
    )


def test_resolve_operand_reads_rung_from_ranked_equivalent() -> None:
    """Verify via_filing_local / via_default markers reach the operand."""
    atom = Atom("H_LIABILITY", frozenset({"M_ACCOUNTS_PAYABLE"}))
    local = RankedEquivalent(
        "us-gaap:AccountsPayable", atom, "near", 2, False, True, rule="via_filing_local"
    )
    operand = resolve_operand(
        lambda term: _query_result(equivalents=(local,)), "+", "x"
    )
    assert operand.provenance == "filing_local"
    default = RankedEquivalent(
        "us-gaap:AccountsPayable", atom, "near", 2, True, False, rule="via_default"
    )
    operand = resolve_operand(
        lambda term: _query_result(equivalents=(default,)), "+", "x"
    )
    assert operand.provenance == "default"


def test_resolve_operand_stated_provenance_wins_over_markers() -> None:
    """Verify a resolver-stated rung is carried through verbatim."""
    atom = Atom("H_LIABILITY", frozenset({"M_ACCOUNTS_PAYABLE"}))
    default = RankedEquivalent(
        "us-gaap:AccountsPayable", atom, "near", 2, True, False, rule="via_default"
    )
    result = _query_result(provenance="gated_claim", equivalents=(default,))
    operand = resolve_operand(lambda term: result, "+", "x")
    assert operand.provenance == "gated_claim"
    assert operand.status == QueryStatus.REPORTED


def _pick_fact(facts: tuple[XbrlFact, ...], qname: str) -> XbrlFact | None:
    """The qname's deduped headline fact: latest period, longest span."""
    seen: dict[tuple, XbrlFact] = {}
    for fact in facts:
        if fact.concept_qname != qname or fact.dimensions:
            continue
        if not isinstance(fact.value, (int, float)):
            continue
        key = (
            fact.value,
            fact.unit,
            fact.period_type,
            fact.start_date,
            fact.end_date,
            fact.instant_date,
        )
        seen[key] = fact
    if not seen:
        return None

    def rank(fact: XbrlFact) -> tuple[str, int]:
        end = fact.end_date or fact.instant_date or ""
        span = 0
        if fact.start_date and fact.end_date:
            span = (
                date.fromisoformat(fact.end_date) - date.fromisoformat(fact.start_date)
            ).days
        return end, span

    return max(seen.values(), key=rank)


def _ladder_resolver(
    facts: tuple[XbrlFact, ...],
    table: ConceptTable,
    record: FilingEvidenceRecord | None,
    evidence_on: bool,
):
    """Resolve terms over one filing's facts through the presumption ladder."""
    taxonomy = table.taxonomy
    groups = tuple(taxonomy.sibling_groups) or None
    qnames = sorted({f.concept_qname for f in facts if f.concept_qname in table})

    def resolve(term: str) -> FinancialQueryResult:
        target = table.tokenize(term)
        ranked = []
        for qname in qnames:
            candidate = table.record(qname)
            target_place = candidate_place = None
            if evidence_on and record is not None:
                entry = record.entry(term)
                target_place = entry.placement_horizon if entry else None
                entry = record.entry(qname)
                candidate_place = entry.placement_horizon if entry else None
            result = classify_ladder_pair(
                target.atom,
                candidate.atom,
                taxonomy.default_coordinates,
                groups,
                target_derived_horizon=target.derived_horizon,
                candidate_derived_horizon=candidate.derived_horizon,
                target_placement_horizon=target_place,
                candidate_placement_horizon=candidate_place,
            )
            if result.tier == UNRELATED:
                continue
            if result.via_filing_local:
                rung = "filing_local"
            elif result.via_default:
                rung = "default"
            elif classify_pair(target.atom, candidate.atom) == UNRELATED:
                rung = "derived"
            else:
                rung = "name"
            key = (
                0 if result.tier == "exact" else 1,
                2 if result.via_default else 1 if result.via_filing_local else 0,
                result.modifier_distance,
                qname,
            )
            ranked.append((key, qname, rung))
        query = FinancialQuery(
            term=term,
            scope=FactScope(accession=record.accession if record else ""),
        )
        if not ranked:
            return FinancialQueryResult(
                query, QueryStatus.UNAVAILABLE, target_atom=target.atom
            )
        ranked.sort(key=lambda item: item[0])
        best = ranked[0][0]
        self_hit = [
            item
            for item in ranked
            if item[1] == term and item[0][0] == best[0] and item[0][2] == best[2]
        ]
        _, chosen, rung = self_hit[0] if self_hit else ranked[0]
        fact = _pick_fact(facts, chosen)
        if fact is None:
            return FinancialQueryResult(
                query, QueryStatus.UNAVAILABLE, target_atom=target.atom
            )
        return FinancialQueryResult(
            query,
            QueryStatus.REPORTED,
            candidate_qnames=(chosen,),
            reported_fact=fact,
            target_atom=target.atom,
            provenance=rung,
        )

    return resolve


def _gated_resolver(
    facts: tuple[XbrlFact, ...],
    table: ConceptTable,
    record: FilingEvidenceRecord | None,
    evidence_on: bool,
):
    """Resolve terms over one filing's facts through per-filing tokenization."""
    qnames = sorted({f.concept_qname for f in facts})

    def tokenized(qname: str):
        if evidence_on and record is not None:
            return table.tokenize(qname, evidence=record.evidence_context(qname))
        return table.tokenize(qname)

    def resolve(term: str) -> FinancialQueryResult:
        target = tokenized(term)
        ranked = []
        for qname in qnames:
            candidate = tokenized(qname)
            tier = classify_pair(target.atom, candidate.atom)
            if tier == UNRELATED:
                continue
            gated = any(match.entry.requires_evidence for match in candidate.matches)
            key = (
                0 if tier == "exact" else 1,
                len(target.atom.modifiers ^ candidate.atom.modifiers),
                qname,
            )
            ranked.append((key, qname, gated))
        query = FinancialQuery(
            term=term,
            scope=FactScope(accession=record.accession if record else ""),
        )
        if not ranked:
            return FinancialQueryResult(
                query, QueryStatus.UNAVAILABLE, target_atom=target.atom
            )
        ranked.sort(key=lambda item: item[0])
        best = ranked[0][0]
        self_hit = [
            item
            for item in ranked
            if item[1] == term and item[0][0] == best[0] and item[0][1] == best[1]
        ]
        _, chosen, gated = self_hit[0] if self_hit else ranked[0]
        fact = _pick_fact(facts, chosen)
        if fact is None:
            return FinancialQueryResult(
                query, QueryStatus.UNAVAILABLE, target_atom=target.atom
            )
        return FinancialQueryResult(
            query,
            QueryStatus.REPORTED,
            candidate_qnames=(chosen,),
            reported_fact=fact,
            target_atom=target.atom,
            provenance="gated_claim" if (evidence_on and gated) else "name",
        )

    return resolve


_FIXTURE_TOTALS = {
    "BBB": "us-gaap:LiabilitiesCurrent",
    "CCC": "us-gaap:LiabilitiesNoncurrent",
}
_FIXTURE_ROLE = "http://example.com/role/BALANCESHEET"


def _fixture_chain_inputs(tmp_path: Path, firm: str):
    """The WS3a ladder fixture filing: bare payables under one horizon total."""
    total = _FIXTURE_TOTALS[firm]
    accession = "0000000002-24-000002" if firm == "BBB" else "0000000003-24-000003"
    facts = (
        XbrlFact(
            accession=AccessionNumber.from_any(accession),
            concept_qname="us-gaap:AccountsPayable",
            value=100.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-12-31",
        ),
        XbrlFact(
            accession=AccessionNumber.from_any(accession),
            concept_qname="us-gaap:CashAndCashEquivalentsAtCarryingValue",
            value=500.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-12-31",
        ),
    )
    facts_path = tmp_path / firm.lower() / "facts.parquet"
    write_facts_parquet(list(facts), facts_path)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "parent_qname": total,
                    "child_qname": "us-gaap:AccountsPayable",
                    "weight": 1.0,
                    "order": 1.0,
                    "role_uri": _FIXTURE_ROLE,
                }
            ]
        ),
        facts_path.parent / "calculation_arcs.parquet",
    )
    entry = CohortEntry(accession=accession, facts_path=facts_path, firm=firm)
    taxonomy = load_domain_taxonomy()
    table = build_concept_table(
        taxonomy, sorted({fact.concept_qname for fact in facts} | {total})
    )
    record = build_filing_evidence(entry, table)
    arcs = (CalculationArc(total, "us-gaap:AccountsPayable", 1.0, 1.0, _FIXTURE_ROLE),)
    return facts, table, record, arcs


@pytest.fixture(scope="module")
def seed_chain_context():
    """Seed cohort table plus evidence index, built once for chain pins."""
    entries = load_seed_cohort()
    table = build_cohort_table(load_domain_taxonomy(), entries)
    index = build_evidence_index(entries, table)
    yield entries, table, index


def _run_spec(spec: ChainSpec, seed_chain_context, tmp_path: Path, evidence_on: bool):
    """Evaluate one benchmark chain in one evidence mode."""
    if spec.cohort == "seed":
        entries, table, index = seed_chain_context
        entry = next(item for item in entries if item.firm == spec.firm)
        folder = entry.facts_path.parent.name
        facts = load_seed_facts(folder)
        arcs = load_seed_calculation_arcs(folder)
        record = index.record(entry.accession)
    else:
        facts, table, record, arcs = _fixture_chain_inputs(tmp_path, spec.firm)
    resolver_factory = _gated_resolver if spec.resolver == "gated" else _ladder_resolver
    resolver = resolver_factory(facts, table, record, evidence_on)
    return evaluate_chain(resolver, spec.terms, arcs), record


def _mediated(result, spec: ChainSpec):
    """The operand resolution for the spec's mediated term."""
    return next(op for op in result.operands if op.term == spec.mediated_term)


def test_benchmark_chains_hold_with_evidence_on_and_off(
    seed_chain_context, tmp_path: Path
) -> None:
    """Verify every benchmark chain: propagation, fact inputs, no upgrade."""
    for spec in CHAIN_SET:
        on, record = _run_spec(spec, seed_chain_context, tmp_path, True)
        off, _ = _run_spec(spec, seed_chain_context, tmp_path, False)
        for result, concept, rung, status, unit, period_key, value in (
            (
                on,
                spec.on_concept,
                spec.on_provenance,
                spec.on_status,
                spec.on_unit,
                spec.on_period_key,
                spec.on_value,
            ),
            (
                off,
                spec.off_concept,
                spec.off_provenance,
                spec.off_status,
                spec.off_unit,
                spec.off_period_key,
                spec.off_value,
            ),
        ):
            operand = _mediated(result, spec)
            assert operand.concept_qname == concept, spec.label
            assert operand.provenance == rung, spec.label
            assert operand.status == QueryStatus[status], spec.label
            assert operand.unit == unit, spec.label
            assert operand.period_key == period_key, spec.label
            assert result.value == value, spec.label
            worst = max((op.status for op in result.operands), key=STATUS_ORDER.index)
            assert result.status == worst, spec.label
        on_operand = _mediated(on, spec)
        off_operand = _mediated(off, spec)
        for on_op, off_op in zip(on.operands, off.operands, strict=True):
            assert STATUS_ORDER.index(on_op.status) >= STATUS_ORDER.index(
                off_op.status
            ), spec.label
        if spec.on_provenance in ("filing_local", "gated_claim"):
            assert on_operand.status == off_operand.status, spec.label
            assert on_operand.provenance != off_operand.provenance, spec.label
        if spec.cohort == "seed" and record is not None:
            assert record.entry(spec.mediated_term) is not None, spec.label


def test_evidence_records_carry_no_values_or_units() -> None:
    """Verify evidence records cannot supply unit/period/value inputs."""
    fields = set(ConceptEvidence.__dataclass_fields__)
    assert "value" not in fields
    assert "unit" not in fields
    assert "instant_date" not in fields
    assert "start_date" not in fields
    assert "end_date" not in fields


def test_compare_compositions_cohort_form() -> None:
    """Verify the cohort form composes the same chain per company."""
    msft = _create_xbrl_facade("msft")
    aapl = _create_xbrl_facade("aapl")
    msft_view = compare_compositions([msft], _FCF_TERMS, fiscal_year=2024, label="FCF")
    aapl_view = compare_compositions([aapl], _FCF_TERMS, fiscal_year=2024, label="FCF")
    assert list(msft_view.cohort_data.values())[0]["composition"] == 74_071_000_000.0
    assert list(aapl_view.cohort_data.values())[0]["composition"] == 108_807_000_000.0
    assert aapl.financials.free_cash_flow == 108_807_000_000.0
