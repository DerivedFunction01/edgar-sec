"""Independent accounting conservation identities and statement roll-up verification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from edgar_sec.engine.xbrl.schema.models import XbrlFact


@dataclass(frozen=True, slots=True)
class IdentityVerification:
    """Individual accounting conservation equation outcome."""

    identity_name: str
    formula: str
    lhs_value: float
    rhs_value: float
    discrepancy: float
    passed: bool
    tolerance: float = 0.15


def _find_fact_value(
    facts: Sequence[XbrlFact],
    concept_qname: str,
    *,
    period_type: str | None = None,
    require_unsegmented: bool = True,
) -> float | None:
    for f in facts:
        if f.concept_qname != concept_qname:
            continue
        if period_type is not None and f.period_type != period_type:
            continue
        if require_unsegmented and f.dimensions:
            continue
        if isinstance(f.value, (int, float)):
            return float(f.value)
    return None


def verify_balance_sheet_identity(
    facts: Sequence[XbrlFact],
    tolerance: float = 0.15,
) -> IdentityVerification | None:
    """Verify standard fundamental balance sheet equation Assets == Liabilities + Equity."""
    assets = _find_fact_value(
        facts, "us-gaap:Assets", period_type="instant"
    ) or _find_fact_value(facts, "us-gaap:Assets")
    liab = _find_fact_value(
        facts, "us-gaap:Liabilities", period_type="instant"
    ) or _find_fact_value(facts, "us-gaap:Liabilities")
    equity = _find_fact_value(
        facts, "us-gaap:StockholdersEquity", period_type="instant"
    ) or _find_fact_value(facts, "us-gaap:StockholdersEquity")

    if assets is None or liab is None or equity is None:
        return None

    rhs = liab + equity
    diff = round(assets - rhs, 4)
    return IdentityVerification(
        identity_name="ID_BS_FUNDAMENTAL",
        formula="Assets == Liabilities + StockholdersEquity",
        lhs_value=round(assets, 4),
        rhs_value=round(rhs, 4),
        discrepancy=diff,
        passed=abs(diff) <= tolerance,
        tolerance=tolerance,
    )


def verify_gross_profit_identity(
    facts: Sequence[XbrlFact],
    tolerance: float = 0.15,
) -> IdentityVerification | None:
    """Verify Income Statement GrossProfit == Revenues - CostOfGoodsSold."""
    gp = _find_fact_value(facts, "us-gaap:GrossProfit")
    rev = _find_fact_value(
        facts, "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    ) or _find_fact_value(facts, "us-gaap:Revenues")
    cogs = _find_fact_value(
        facts, "us-gaap:CostOfGoodsAndServicesSold"
    ) or _find_fact_value(facts, "us-gaap:CostOfRevenue")

    if gp is None or rev is None or cogs is None:
        return None

    rhs = rev - cogs
    diff = round(gp - rhs, 4)
    return IdentityVerification(
        identity_name="ID_IS_GROSS_PROFIT",
        formula="GrossProfit == Revenues - CostOfRevenue",
        lhs_value=round(gp, 4),
        rhs_value=round(rhs, 4),
        discrepancy=diff,
        passed=abs(diff) <= tolerance,
        tolerance=tolerance,
    )


def verify_operating_income_identity(
    facts: Sequence[XbrlFact],
    tolerance: float = 0.15,
) -> IdentityVerification | None:
    """Verify OperatingIncomeLoss == GrossProfit - OperatingExpenses."""
    opinc = _find_fact_value(facts, "us-gaap:OperatingIncomeLoss")
    gp = _find_fact_value(facts, "us-gaap:GrossProfit")
    if opinc is None or gp is None:
        return None

    rnd = _find_fact_value(facts, "us-gaap:ResearchAndDevelopmentExpense") or 0.0
    sm = _find_fact_value(facts, "us-gaap:SellingAndMarketingExpense") or 0.0
    ga = _find_fact_value(facts, "us-gaap:GeneralAndAdministrativeExpense") or 0.0
    opex_total = (
        _find_fact_value(facts, "us-gaap:OperatingExpenses")
        if (rnd == 0.0 and sm == 0.0 and ga == 0.0)
        else (rnd + sm + ga)
    )

    if opex_total is None or opex_total == 0.0:
        return None

    rhs = gp - opex_total
    diff = round(opinc - rhs, 4)
    return IdentityVerification(
        identity_name="ID_IS_OPERATING_INCOME",
        formula="OperatingIncome == GrossProfit - OperatingExpenses",
        lhs_value=round(opinc, 4),
        rhs_value=round(rhs, 4),
        discrepancy=diff,
        passed=abs(diff) <= tolerance,
        tolerance=tolerance,
    )


def verify_dimensional_rollup(
    facts: Sequence[XbrlFact],
    total_qname: str,
    axis_qname: str,
    tolerance: float = 0.15,
) -> IdentityVerification | None:
    """Verify sum of dimensional coordinate member facts equals unsegmented total."""
    total_val = _find_fact_value(facts, total_qname, require_unsegmented=True)
    if total_val is None:
        return None

    member_vals: list[float] = []
    for f in facts:
        if f.concept_qname == total_qname and axis_qname in f.dimensions:
            if isinstance(f.value, (int, float)):
                member_vals.append(float(f.value))

    if not member_vals:
        return None

    sum_members = sum(member_vals)
    diff = round(total_val - sum_members, 4)
    return IdentityVerification(
        identity_name=f"ID_DIM_ROLLUP_{total_qname.split(':')[-1]}",
        formula=f"Total({total_qname}) == Sum({axis_qname} members)",
        lhs_value=round(total_val, 4),
        rhs_value=round(sum_members, 4),
        discrepancy=diff,
        passed=abs(diff) <= tolerance,
        tolerance=tolerance,
    )


def verify_all_accounting_identities(
    facts: Sequence[XbrlFact],
    tolerance: float = 0.15,
) -> tuple[IdentityVerification, ...]:
    """Run all standard accounting conservation checks across available facts."""
    results: list[IdentityVerification] = []
    bs = verify_balance_sheet_identity(facts, tolerance=tolerance)
    if bs is not None:
        results.append(bs)

    gp = verify_gross_profit_identity(facts, tolerance=tolerance)
    if gp is not None:
        results.append(gp)

    op = verify_operating_income_identity(facts, tolerance=tolerance)
    if op is not None:
        results.append(op)

    return tuple(results)
