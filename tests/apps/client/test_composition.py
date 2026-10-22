"""Tests pinning composed-chain semantics: status, veto, compatibility."""

from edgar_sec.apps.client.comparison import compare_compositions
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.solve.query import QueryStatus
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


def test_compare_compositions_cohort_form() -> None:
    """Verify the cohort form composes the same chain per company."""
    msft = _create_xbrl_facade("msft")
    aapl = _create_xbrl_facade("aapl")
    msft_view = compare_compositions([msft], _FCF_TERMS, fiscal_year=2024, label="FCF")
    aapl_view = compare_compositions([aapl], _FCF_TERMS, fiscal_year=2024, label="FCF")
    assert list(msft_view.cohort_data.values())[0]["composition"] == 74_071_000_000.0
    assert list(aapl_view.cohort_data.values())[0]["composition"] == 108_807_000_000.0
    assert aapl.financials.free_cash_flow == 108_807_000_000.0
