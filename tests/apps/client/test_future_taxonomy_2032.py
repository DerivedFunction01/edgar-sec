"""Formal proof of zero-knowledge generalization on unknown 2032 taxonomy."""

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    FilingXbrl,
    LinkbaseBundle,
    XbrlFact,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.apps.client.test_xbrl import _create_xbrl_facade


def _build_quantum_dynamics_2032_filing() -> Xbrl:
    acc = AccessionNumber("0009999999-32-000001")
    cik = Cik(9999999)

    facts = (
        # Multi-year Duration P&L (Inverted/novel syntax)
        XbrlFact(
            acc,
            "qd32:RevenuesEnterpriseQuantumComputeCloud",
            520_000_000_000.0,
            end_date="2032-12-31",
            start_date="2032-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:RevenuesEnterpriseQuantumComputeCloud",
            460_000_000_000.0,
            end_date="2031-12-31",
            start_date="2031-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:HardwareCryogenicServerCosts",
            180_000_000_000.0,
            end_date="2032-12-31",
            start_date="2032-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:HardwareCryogenicServerCosts",
            165_000_000_000.0,
            end_date="2031-12-31",
            start_date="2031-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:ProfitGrossQuantum",
            340_000_000_000.0,
            end_date="2032-12-31",
            start_date="2032-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:ProfitGrossQuantum",
            295_000_000_000.0,
            end_date="2031-12-31",
            start_date="2031-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:ResearchAndDevelopmentExpenseQuantumAlgorithm",
            95_000_000_000.0,
            end_date="2032-12-31",
            start_date="2032-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:SalesAndMarketingExpenseAutonomousEnterprise",
            45_000_000_000.0,
            end_date="2032-12-31",
            start_date="2032-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:OperatingExpensesQuantum",
            140_000_000_000.0,
            end_date="2032-12-31",
            start_date="2032-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:IncomeLossFromOperations",
            200_000_000_000.0,
            end_date="2032-12-31",
            start_date="2032-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:TaxProvisionIncome",
            40_000_000_000.0,
            end_date="2032-12-31",
            start_date="2032-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:IncomeOrLossNet",
            160_000_000_000.0,
            end_date="2032-12-31",
            start_date="2032-01-01",
        ),
        XbrlFact(
            acc,
            "qd32:IncomeOrLossNet",
            140_000_000_000.0,
            end_date="2031-12-31",
            start_date="2031-01-01",
        ),
        # Balance Sheet & Capital Debt (Instant)
        XbrlFact(
            acc,
            "qd32:AssetsProcessorQubitSuperconductingTotal",
            850_000_000_000.0,
            period_type="instant",
            instant_date="2032-12-31",
        ),
        XbrlFact(
            acc,
            "qd32:CurrentCommercialPaperQuantum",
            30_000_000_000.0,
            period_type="instant",
            instant_date="2032-12-31",
        ),
        XbrlFact(
            acc,
            "qd32:DebenturesConvertibleZeroCouponQuantum",
            120_000_000_000.0,
            period_type="instant",
            instant_date="2032-12-31",
        ),
        XbrlFact(
            acc,
            "qd32:StockholdersEquityQuantum",
            500_000_000_000.0,
            period_type="instant",
            instant_date="2032-12-31",
        ),
        # Dimensional Derivatives with Risk Hypercube Axis
        XbrlFact(
            acc,
            "qd32:HedgingDerivativeFairValueAsset",
            15_000_000_000.0,
            period_type="instant",
            instant_date="2032-12-31",
            dimensions={
                "us-gaap-2032:DerivativeInstrumentRiskAxis": "us-gaap-2032:InterestRateContractMember"
            },
        ),
        XbrlFact(
            acc,
            "qd32:SyntheticFxForwardContractLiability",
            8_000_000_000.0,
            period_type="instant",
            instant_date="2032-12-31",
            dimensions={
                "us-gaap-2032:DerivativeInstrumentRiskAxis": "us-gaap-2032:ForeignExchangeContractMember"
            },
        ),
    )

    arcs = (
        CalculationArc(
            "qd32:ProfitGrossQuantum",
            "qd32:RevenuesEnterpriseQuantumComputeCloud",
            1.0,
        ),
        CalculationArc(
            "qd32:ProfitGrossQuantum", "qd32:HardwareCryogenicServerCosts", -1.0
        ),
        CalculationArc(
            "qd32:OperatingExpensesQuantum",
            "qd32:ResearchAndDevelopmentExpenseQuantumAlgorithm",
            1.0,
        ),
        CalculationArc(
            "qd32:OperatingExpensesQuantum",
            "qd32:SalesAndMarketingExpenseAutonomousEnterprise",
            1.0,
        ),
        CalculationArc("qd32:IncomeLossFromOperations", "qd32:ProfitGrossQuantum", 1.0),
        CalculationArc(
            "qd32:IncomeLossFromOperations", "qd32:OperatingExpensesQuantum", -1.0
        ),
        CalculationArc("qd32:IncomeOrLossNet", "qd32:IncomeLossFromOperations", 1.0),
        CalculationArc("qd32:IncomeOrLossNet", "qd32:TaxProvisionIncome", -1.0),
    )

    bundle = FilingXbrl(
        accession=acc,
        cik=cik,
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def test_future_2032_taxonomy_zero_knowledge_solving() -> None:
    """Prove unknown 2032 firm is solved, balanced, and verified via atoms."""
    qd32 = _build_quantum_dynamics_2032_filing()

    # 1. Statement Root Discovery with Inverted Syntax
    inc = qd32.statements.income_statement()
    assert inc.root is not None
    assert inc.root.concept_qname == "qd32:IncomeOrLossNet"
    assert inc.root.value == 160_000_000_000.0
    assert "2032" in inc.years
    assert "2031" in inc.years

    # 2. Anti-Chain Topological Summation Guarantee
    outcome = inc.verify_antichain()
    assert outcome.is_valid is True
    assert outcome.discrepancy == 0.0

    # 3. Multi-Column Accounting Table Formatting
    table_str = inc.render_table()
    assert "[INCOME STATEMENT]" in table_str
    assert "FY 2032" in table_str
    assert "FY 2031" in table_str
    assert "$520,000,000,000" in table_str
    assert "$160,000,000,000" in table_str

    # 4. Dynamic Financials via Subatomic Coordinates
    fin = qd32.financials
    assert fin.revenue == 520_000_000_000.0
    assert fin.gross_profit == 340_000_000_000.0
    assert fin.operating_income == 200_000_000_000.0
    assert fin.net_income == 160_000_000_000.0
    assert fin.total_assets == 850_000_000_000.0

    # 5. Derivatives with Graph Risk Decomposition
    derivs = fin.derivatives
    assert len(derivs.positions) == 2
    ir_positions = derivs.by_risk("interest_rate")
    assert len(ir_positions) == 1
    assert ir_positions[0].concept_qname == "qd32:HedgingDerivativeFairValueAsset"
    fx_positions = derivs.by_risk("foreign_exchange")
    assert len(fx_positions) == 1
    assert fx_positions[0].concept_qname == "qd32:SyntheticFxForwardContractLiability"

    # 6. Debt Tranches
    debt = fin.debt
    assert debt.commercial_paper == 30_000_000_000.0
    assert debt.long_term_debt == 120_000_000_000.0
    assert debt.total_debt == 150_000_000_000.0


def test_future_2032_cross_company_and_time_comparison() -> None:
    """Prove cross-entity comparison between 2032 firm and 2024 ground fixtures."""
    qd32 = _build_quantum_dynamics_2032_filing()
    aapl = _create_xbrl_facade("aapl")
    msft = _create_xbrl_facade("msft")

    comp_view = qd32.compare([aapl, msft])
    table = comp_view.render_table()
    assert "Revenue" in table
    assert "Operating Margin" in table
    assert "Net Margin" in table

    df = comp_view.to_dataframe()
    assert len(df) > 0
