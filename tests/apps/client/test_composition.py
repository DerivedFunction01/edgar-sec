"""Tests pinning composed-chain semantics: status, veto, compatibility."""

from edgar_sec.apps.client.comparison import compare_compositions
from edgar_sec.apps.client.composition import resolve_operand
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle, XbrlFact
from edgar_sec.engine.xbrl.solve.equivalence import RankedEquivalent
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryResult,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import load_seed_calculation_arcs, load_seed_facts

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


def test_compare_compositions_cohort_form() -> None:
    """Verify the cohort form composes the same chain per company."""
    msft = _create_xbrl_facade("msft")
    aapl = _create_xbrl_facade("aapl")
    msft_view = compare_compositions([msft], _FCF_TERMS, fiscal_year=2024, label="FCF")
    aapl_view = compare_compositions([aapl], _FCF_TERMS, fiscal_year=2024, label="FCF")
    assert list(msft_view.cohort_data.values())[0]["composition"] == 74_071_000_000.0
    assert list(aapl_view.cohort_data.values())[0]["composition"] == 108_807_000_000.0
    assert aapl.financials.free_cash_flow == 108_807_000_000.0
