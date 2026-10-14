"""Unit tests for Rendered Form ground-truth verifier and double-counting detector."""

from edgar_sec.engine.xbrl.schema.models import ConceptBreakdown, GranularComponent
from edgar_sec.engine.xbrl.solve.verification import DoubleCountVerifier


def test_extract_printed_row_value_multicurrency() -> None:
    """Verify parsing of international currency amounts including EUR, JPY, and GBP."""
    table_text = """
    Gross Profit .............. $ 169,295
    Net Loss .................. $ (5,200)
    Attached Dollar Loss ...... $(5,200)
    Spaced Dollar Paren ....... ( $ 5,200 )
    European Operating Revenue  € 45,000
    European Attached Revenue . €45,000
    European Derivative Loss .. € (3,200)
    European Attached Loss .... €(3,200)
    European Enclosed Loss .... (€3,200)
    European Spaced Paren ..... ( € 3,200 )
    Tokyo Treasury Gain ....... ¥ 1,250,000
    Tokyo Attached Gain ....... ¥1,250,000
    Tokyo Hedging Expense ..... ¥ (750,000)
    Tokyo Attached Loss ....... ¥(750,000)
    Tokyo Enclosed Loss ....... (¥750,000)
    Tokyo Spaced Paren ........ ( ¥ 750,000 )
    London Subsidiary Total ... £ 88,500
    Multi-Column Euro Row ..... € 45,000  € 38,000
    Multi-Column Yen Row ...... ¥ (750,000)  ¥ (500,000)
    """
    assert (
        DoubleCountVerifier.extract_printed_row_value(table_text, "Gross Profit")
        == 169295.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(table_text, "Net Loss") == -5200.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(
            table_text, "Attached Dollar Loss"
        )
        == -5200.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(table_text, "Spaced Dollar Paren")
        == -5200.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(
            table_text, "European Operating Revenue"
        )
        == 45000.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(
            table_text, "European Attached Revenue"
        )
        == 45000.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(
            table_text, "European Derivative Loss"
        )
        == -3200.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(
            table_text, "European Attached Loss"
        )
        == -3200.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(
            table_text, "European Enclosed Loss"
        )
        == -3200.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(
            table_text, "European Spaced Paren"
        )
        == -3200.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(table_text, "Tokyo Treasury Gain")
        == 1250000.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(table_text, "Tokyo Attached Gain")
        == 1250000.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(
            table_text, "Tokyo Hedging Expense"
        )
        == -750000.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(table_text, "Tokyo Attached Loss")
        == -750000.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(table_text, "Tokyo Enclosed Loss")
        == -750000.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(table_text, "Tokyo Spaced Paren")
        == -750000.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(
            table_text, "London Subsidiary Total"
        )
        == 88500.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(
            table_text, "Multi-Column Euro Row"
        )
        == 45000.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(
            table_text, "Multi-Column Yen Row"
        )
        == -750000.0
    )
    assert (
        DoubleCountVerifier.extract_printed_row_value(table_text, "Nonexistent") is None
    )


def test_verify_breakdown_clean_match() -> None:
    """Verify valid component breakdown matching rendered table without double counting."""
    table_text = "Total Derivative Assets ........ $ 230"
    bd = ConceptBreakdown(
        target_concept="us-gaap:DerivativeAssets",
        total_value=230.0,
        components=(
            GranularComponent("InterestRateContracts", 150.0, 1.0),
            GranularComponent("ForeignExchangeContracts", 80.0, 1.0),
        ),
        is_balanced=True,
        discrepancy=0.0,
    )
    res = DoubleCountVerifier.verify_breakdown(
        table_text, bd, "Total Derivative Assets"
    )
    assert res.is_valid
    assert not res.is_double_counted
    assert res.printed_value == 230.0
    assert res.derived_value == 230.0


def test_verify_breakdown_detects_double_counting_parent() -> None:
    """Verify detection when constituent set includes the target parent itself."""
    table_text = "Total Derivative Assets ........ $ 230"
    bd = ConceptBreakdown(
        target_concept="us-gaap:DerivativeAssets",
        total_value=460.0,
        components=(
            GranularComponent("InterestRateContracts", 150.0, 1.0),
            GranularComponent("ForeignExchangeContracts", 80.0, 1.0),
            GranularComponent("us-gaap:DerivativeAssets", 230.0, 1.0),
        ),
        is_balanced=False,
        discrepancy=230.0,
    )
    res = DoubleCountVerifier.verify_breakdown(
        table_text, bd, "Total Derivative Assets"
    )
    assert not res.is_valid
    assert res.is_double_counted
    assert "target parent included" in res.message


def test_verify_breakdown_detects_2x_sum() -> None:
    """Verify detection when component sum equals 2x printed total."""
    table_text = "Total Revenues ........ $ 100"
    bd = ConceptBreakdown(
        target_concept="us-gaap:Revenues",
        total_value=200.0,
        components=(
            GranularComponent("ProductRevenue", 100.0, 1.0),
            GranularComponent("ServiceRevenue", 100.0, 1.0),
        ),
        is_balanced=True,
        discrepancy=0.0,
    )
    res = DoubleCountVerifier.verify_breakdown(table_text, bd, "Total Revenues")
    assert not res.is_valid
    assert res.is_double_counted
    assert "2x printed total" in res.message


def test_verify_breakdown_detects_gross_net_conflation() -> None:
    """Verify detection when gross and net are aggregated without offsetting."""
    table_text = "Derivative Assets Net ........ $ 230"
    bd = ConceptBreakdown(
        target_concept="us-gaap:DerivativeAssetsNet",
        total_value=510.0,
        components=(
            GranularComponent("DerivativeAssetsGross", 280.0, 1.0),
            GranularComponent("DerivativeAssetsNet", 230.0, 1.0),
        ),
        is_balanced=False,
        discrepancy=280.0,
    )
    res = DoubleCountVerifier.verify_breakdown(table_text, bd, "Derivative Assets Net")
    assert not res.is_valid
    assert res.is_double_counted


def test_verify_breakdown_euro_clean_match() -> None:
    """Verify valid European component breakdown in EUR without double counting."""
    table_text = "European Derivative Assets ........ € 45,000"
    bd = ConceptBreakdown(
        target_concept="us-gaap:DerivativeAssets",
        total_value=45000.0,
        components=(
            GranularComponent("InterestRateSwaps", 30000.0, 1.0),
            GranularComponent("ForeignExchangeForwards", 15000.0, 1.0),
        ),
        is_balanced=True,
        discrepancy=0.0,
    )
    res = DoubleCountVerifier.verify_breakdown(
        table_text, bd, "European Derivative Assets"
    )
    assert res.is_valid
    assert not res.is_double_counted
    assert res.printed_value == 45000.0
    assert res.derived_value == 45000.0


def test_verify_breakdown_euro_detects_double_counting_parent() -> None:
    """Verify detection when constituent set includes the target parent in EUR."""
    table_text = "European Operating Assets ........ € 45,000"
    bd = ConceptBreakdown(
        target_concept="us-gaap:OperatingAssets",
        total_value=90000.0,
        components=(
            GranularComponent("InterestRateSwaps", 30000.0, 1.0),
            GranularComponent("ForeignExchangeForwards", 15000.0, 1.0),
            GranularComponent("us-gaap:OperatingAssets", 45000.0, 1.0),
        ),
        is_balanced=False,
        discrepancy=45000.0,
    )
    res = DoubleCountVerifier.verify_breakdown(
        table_text, bd, "European Operating Assets"
    )
    assert not res.is_valid
    assert res.is_double_counted
    assert "target parent included" in res.message


def test_verify_breakdown_euro_detects_2x_sum() -> None:
    """Verify detection when Euro component sum equals 2x printed total."""
    table_text = "European Operating Revenue ........ € 45,000"
    bd = ConceptBreakdown(
        target_concept="us-gaap:Revenues",
        total_value=90000.0,
        components=(
            GranularComponent("ProductRevenue", 45000.0, 1.0),
            GranularComponent("ServiceRevenue", 45000.0, 1.0),
        ),
        is_balanced=True,
        discrepancy=0.0,
    )
    res = DoubleCountVerifier.verify_breakdown(
        table_text, bd, "European Operating Revenue"
    )
    assert not res.is_valid
    assert res.is_double_counted
    assert "2x printed total" in res.message


def test_verify_breakdown_jpy_clean_match() -> None:
    """Verify valid Tokyo component breakdown in JPY without double counting."""
    table_text = "Tokyo Derivative Assets ........ ¥ 1,250,000"
    bd = ConceptBreakdown(
        target_concept="us-gaap:DerivativeAssets",
        total_value=1250000.0,
        components=(
            GranularComponent("InterestRateSwaps", 750000.0, 1.0),
            GranularComponent("ForeignExchangeContracts", 500000.0, 1.0),
        ),
        is_balanced=True,
        discrepancy=0.0,
    )
    res = DoubleCountVerifier.verify_breakdown(
        table_text, bd, "Tokyo Derivative Assets"
    )
    assert res.is_valid
    assert not res.is_double_counted
    assert res.printed_value == 1250000.0
    assert res.derived_value == 1250000.0


def test_verify_breakdown_jpy_detects_double_counting_parent() -> None:
    """Verify detection when constituent set includes target parent in JPY."""
    table_text = "Tokyo Derivative Assets ........ ¥ 1,250,000"
    bd = ConceptBreakdown(
        target_concept="us-gaap:DerivativeAssets",
        total_value=2500000.0,
        components=(
            GranularComponent("InterestRateSwaps", 750000.0, 1.0),
            GranularComponent("ForeignExchangeContracts", 500000.0, 1.0),
            GranularComponent("us-gaap:DerivativeAssets", 1250000.0, 1.0),
        ),
        is_balanced=False,
        discrepancy=1250000.0,
    )
    res = DoubleCountVerifier.verify_breakdown(
        table_text, bd, "Tokyo Derivative Assets"
    )
    assert not res.is_valid
    assert res.is_double_counted
    assert "target parent included" in res.message


def test_verify_breakdown_jpy_detects_gross_net_conflation() -> None:
    """Verify detection when gross and net are aggregated in JPY without offsetting."""
    table_text = "Tokyo Derivative Net Assets ........ ¥ 1,250,000"
    bd = ConceptBreakdown(
        target_concept="us-gaap:DerivativeAssetsNet",
        total_value=3000000.0,
        components=(
            GranularComponent("DerivativeAssetsGross", 1750000.0, 1.0),
            GranularComponent("DerivativeAssetsNet", 1250000.0, 1.0),
        ),
        is_balanced=False,
        discrepancy=1750000.0,
    )
    res = DoubleCountVerifier.verify_breakdown(
        table_text, bd, "Tokyo Derivative Net Assets"
    )
    assert not res.is_valid
    assert res.is_double_counted


def test_verify_breakdown_negative_euro_and_jpy() -> None:
    """Verify negative printed amounts in EUR and JPY with balanced negative breakdowns."""
    eur_table = "European Derivative Loss ........ € (3,200)"
    eur_bd = ConceptBreakdown(
        target_concept="us-gaap:DerivativeLoss",
        total_value=-3200.0,
        components=(GranularComponent("FXLoss", -3200.0, 1.0),),
        is_balanced=True,
        discrepancy=0.0,
    )
    eur_res = DoubleCountVerifier.verify_breakdown(
        eur_table, eur_bd, "European Derivative Loss"
    )
    assert eur_res.is_valid
    assert not eur_res.is_double_counted
    assert eur_res.printed_value == -3200.0
    assert eur_res.derived_value == -3200.0

    jpy_table = "Tokyo Hedging Expense .......... ¥ (750,000)"
    jpy_bd = ConceptBreakdown(
        target_concept="us-gaap:HedgingExpense",
        total_value=-750000.0,
        components=(GranularComponent("SwapsExpense", -750000.0, 1.0),),
        is_balanced=True,
        discrepancy=0.0,
    )
    jpy_res = DoubleCountVerifier.verify_breakdown(
        jpy_table, jpy_bd, "Tokyo Hedging Expense"
    )
    assert jpy_res.is_valid
    assert not jpy_res.is_double_counted
    assert jpy_res.printed_value == -750000.0
    assert jpy_res.derived_value == -750000.0
