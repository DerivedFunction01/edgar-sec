"""Independent accounting conservation identities and statement roll-up verification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy


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


@dataclass(frozen=True, slots=True)
class _Slot:
    """An identity term defined by a canonical concept's atom coordinate.

    The canonical fact is the witness; absent it, facts fill by atom
    (exact, or subsumed for the revenue / cost-of-revenue slots).
    """

    canonical: str
    accept_subsumed: bool = False


_ASSETS = _Slot("us-gaap:Assets")
_LIABILITIES = _Slot("us-gaap:Liabilities")
_EQUITY = _Slot("us-gaap:StockholdersEquity")
_GROSS_PROFIT = _Slot("us-gaap:GrossProfit")
_REVENUE = _Slot("us-gaap:Revenues", accept_subsumed=True)
_COST_OF_REVENUE = _Slot("us-gaap:CostOfRevenue", accept_subsumed=True)
_OPERATING_INCOME = _Slot("us-gaap:OperatingIncomeLoss")
_OPERATING_EXPENSES = _Slot("us-gaap:OperatingExpenses")
_RD_EXPENSE = _Slot("us-gaap:ResearchAndDevelopmentExpense")
_SM_EXPENSE = _Slot("us-gaap:SellingAndMarketingExpense")
_GA_EXPENSE = _Slot("us-gaap:GeneralAndAdministrativeExpense")


@lru_cache(maxsize=1)
def _taxonomy() -> DomainTaxonomy:
    return load_domain_taxonomy()


@lru_cache(maxsize=None)
def _atom_of(concept_qname: str) -> Atom:
    lexicon = _taxonomy().token_lexicon
    assert lexicon is not None
    atom, _, _, _ = decompose_concept(concept_qname, lexicon)
    return atom


def _unique_value(matches: list[XbrlFact]) -> float | None:
    """The single value across matches, or None when contexts/values disagree."""
    contexts = {
        (
            f.unit,
            f.period_type,
            f.start_date,
            f.end_date,
            f.instant_date,
            tuple(sorted(f.dimensions.items())),
        )
        for f in matches
    }
    values = {float(f.value) for f in matches}
    if len(contexts) != 1 or len(values) != 1:
        return None
    return next(iter(values))


def _find_slot_value(
    facts: Sequence[XbrlFact],
    slot: _Slot,
    *,
    period_type: str | None = None,
    require_unsegmented: bool = True,
) -> float | None:
    """Find a fact filling an identity slot: witness first, then atom fill."""
    slot_atom = _atom_of(slot.canonical)
    eligible = [
        f
        for f in facts
        if (period_type is None or f.period_type == period_type)
        and (not require_unsegmented or not f.dimensions)
        and isinstance(f.value, (int, float))
    ]
    witness = _unique_value([f for f in eligible if f.concept_qname == slot.canonical])
    if witness is not None:
        return witness
    matches = [
        f
        for f in eligible
        if _atom_of(f.concept_qname) == slot_atom
        or (slot.accept_subsumed and _atom_of(f.concept_qname).is_a(slot_atom))
    ]
    return _unique_value(matches)


def _find_fact_value(
    facts: Sequence[XbrlFact],
    concept_qname: str,
    *,
    period_type: str | None = None,
    require_unsegmented: bool = True,
) -> float | None:
    matches = [
        f
        for f in facts
        if f.concept_qname == concept_qname
        and (period_type is None or f.period_type == period_type)
        and (not require_unsegmented or not f.dimensions)
        and isinstance(f.value, (int, float))
    ]
    return _unique_value(matches)


def verify_balance_sheet_identity(
    facts: Sequence[XbrlFact],
    tolerance: float = 0.15,
    *,
    scope: FactScope | None = None,
) -> IdentityVerification | None:
    """Verify standard fundamental balance sheet equation Assets == Liabilities + Equity."""
    selected = scope.select(list(facts)) if scope else facts
    assets = _find_slot_value(selected, _ASSETS, period_type="instant")
    liab = _find_slot_value(selected, _LIABILITIES, period_type="instant")
    equity = _find_slot_value(selected, _EQUITY, period_type="instant")

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
    *,
    scope: FactScope | None = None,
) -> IdentityVerification | None:
    """Verify Income Statement GrossProfit == Revenues - CostOfGoodsSold."""
    selected = scope.select(list(facts)) if scope else facts
    gp = _find_slot_value(selected, _GROSS_PROFIT, period_type="duration")
    rev = _find_slot_value(selected, _REVENUE, period_type="duration")
    cogs = _find_slot_value(selected, _COST_OF_REVENUE, period_type="duration")

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
    *,
    scope: FactScope | None = None,
) -> IdentityVerification | None:
    """Verify OperatingIncomeLoss == GrossProfit - OperatingExpenses."""
    selected = scope.select(list(facts)) if scope else facts
    opinc = _find_slot_value(selected, _OPERATING_INCOME, period_type="duration")
    gp = _find_slot_value(selected, _GROSS_PROFIT, period_type="duration")
    if opinc is None or gp is None:
        return None

    rnd = _find_slot_value(selected, _RD_EXPENSE, period_type="duration") or 0.0
    sm = _find_slot_value(selected, _SM_EXPENSE, period_type="duration") or 0.0
    ga = _find_slot_value(selected, _GA_EXPENSE, period_type="duration") or 0.0
    opex_total = (
        _find_slot_value(selected, _OPERATING_EXPENSES, period_type="duration")
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
    *,
    scope: FactScope | None = None,
) -> IdentityVerification | None:
    """Verify sum of dimensional coordinate member facts equals unsegmented total."""
    selected = scope.select(list(facts)) if scope else facts
    total_val = _find_fact_value(selected, total_qname, require_unsegmented=True)
    if total_val is None:
        return None

    member_vals: list[float] = []
    for f in selected:
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
    *,
    scope: FactScope | None = None,
) -> tuple[IdentityVerification, ...]:
    """Run all standard accounting conservation checks across available facts."""
    selected = scope.select(list(facts)) if scope else facts
    results: list[IdentityVerification] = []
    bs = verify_balance_sheet_identity(selected, tolerance=tolerance)
    if bs is not None:
        results.append(bs)

    gp = verify_gross_profit_identity(selected, tolerance=tolerance)
    if gp is not None:
        results.append(gp)

    op = verify_operating_income_identity(selected, tolerance=tolerance)
    if op is not None:
        results.append(op)

    return tuple(results)
