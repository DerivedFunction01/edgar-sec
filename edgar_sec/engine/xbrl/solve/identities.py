"""Independent accounting conservation identities and statement roll-up verification."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    residual_counts,
)
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


def signed_rollforward_total(
    opening: float | None,
    components: Iterable[tuple[float | None, float]],
) -> float | None:
    """Opening plus signed components; None when the opening is unfiled.

    A component whose value is None contributes nothing; a caller whose
    leg is required must guard that leg itself before delegating.
    """
    if opening is None:
        return None
    total = opening
    for value, sign in components:
        if value is not None:
            total += sign * value
    return total


def identity_discrepancy(
    reported: float | None, computed: float | None
) -> float | None:
    """Reported minus computed, or None when either side is missing."""
    if reported is None or computed is None:
        return None
    return reported - computed


def identity_verified(
    reported: float | None, computed: float | None, tolerance: float = 1.0
) -> bool | None:
    """Whether the identity gap is within tolerance, when both sides exist."""
    gap = identity_discrepancy(reported, computed)
    return None if gap is None else abs(gap) <= tolerance


@dataclass(frozen=True, slots=True)
class _Slot:
    """An identity term defined by an atom coordinate."""

    atom: Atom
    accept_subsumed: bool = False


_ASSETS = _Slot(Atom("H_ASSET", frozenset()))
_LIABILITIES = _Slot(Atom("H_LIABILITY", frozenset()))
_EQUITY = _Slot(Atom("H_EQUITY", frozenset()))
_GROSS_PROFIT = _Slot(Atom("H_INCOME", frozenset({"M_GROSS_MARGIN"})))
_REVENUE = _Slot(Atom("H_REVENUE", frozenset()), accept_subsumed=True)
_COST_OF_REVENUE = _Slot(Atom("H_COST", frozenset()), accept_subsumed=True)
_OPERATING_INCOME = _Slot(Atom("H_INCOME", frozenset({"M_OPERATING"})))
_OPERATING_EXPENSES = _Slot(Atom("H_EXPENSE", frozenset({"M_OPERATING"})))
_RD_EXPENSE = _Slot(Atom("H_EXPENSE", frozenset({"M_RD"})))
_SM_EXPENSE = _Slot(Atom("H_EXPENSE", frozenset()))
_GA_EXPENSE = _Slot(Atom("H_EXPENSE", frozenset({"M_SGA"})))
_EPS_BASIC = _Slot(Atom("H_UNIT_RATE", frozenset({"V_BASIC"})))
_EPS_DILUTED = _Slot(Atom("H_UNIT_RATE", frozenset({"V_DILUTED"})))
_SHARES_BASIC = _Slot(
    Atom(
        "H_SHARE",
        frozenset({"M_SHARES_OUTSTANDING", "M_WEIGHTED_AVERAGE", "V_BASIC"}),
    )
)
_SHARES_DILUTED = _Slot(
    Atom(
        "H_SHARE",
        frozenset({"M_SHARES_OUTSTANDING", "M_WEIGHTED_AVERAGE", "V_DILUTED"}),
    )
)
# EPS numerator tiers, most specific first: income attributable or
# available to common, then the net bottom line, then the filed total.
_NUMERATOR_TIERS = (
    _Slot(
        Atom("H_INCOME", frozenset({"M_COMMON", "M_NET_BOTTOMLINE"})),
        accept_subsumed=True,
    ),
    _Slot(Atom("H_INCOME", frozenset({"M_NET_BOTTOMLINE"}))),
    _Slot(Atom("H_INCOME", frozenset())),
)


@lru_cache(maxsize=1)
def _taxonomy() -> DomainTaxonomy:
    return load_domain_taxonomy()


def movement_sign(scope: str, role: str, side: str | None = None) -> float:
    """Declared valence of a movement role, via the cached taxonomy."""
    return _taxonomy().movement_sign(scope, role, side)


def negative_roles(scope: str, side: str) -> frozenset[str]:
    """Roles declared negative for one side of a rollforward scope."""
    return frozenset(
        record.role
        for record in _taxonomy().valences
        if record.scope == scope and record.side == side and record.sign < 0
    )


def evaluate_composition(
    scope: str, values: Mapping[str, float | None]
) -> float | None:
    """Signed sum over a declared composition's present roles.

    None when none of the composition's roles carries a value: the
    identity does not fire on absent legs.
    """
    taxonomy = _taxonomy()
    total = 0.0
    fired = False
    for role in taxonomy.composition_roles(scope):
        value = values.get(role)
        if value is not None:
            total += taxonomy.movement_sign(scope, role) * value
            fired = True
    return total if fired else None


def balance_sign(head: str) -> float:
    """Double-entry sign of a prime head's declared normal balance."""
    prime = _taxonomy().prime_head(head)
    if prime is None:
        raise KeyError(f"no prime head declared for {head}")
    return 1.0 if prime.normal_balance == "DEBIT" else -1.0


@lru_cache(maxsize=None)
def _atom_and_residuals(concept_qname: str) -> tuple[Atom, int]:
    lexicon = _taxonomy().token_lexicon
    assert lexicon is not None
    atom, residuals, _, _ = decompose_concept(concept_qname, lexicon)
    intent, _ = residual_counts(residuals)
    return atom, intent


def _atom_of(concept_qname: str) -> Atom:
    return _atom_and_residuals(concept_qname)[0]


def _intent_residuals_of(concept_qname: str) -> int:
    return _atom_and_residuals(concept_qname)[1]


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


def _slot_matches(
    facts: Sequence[XbrlFact],
    slot: _Slot,
    *,
    period_type: str | None = None,
    require_unsegmented: bool = True,
) -> list[XbrlFact]:
    """Facts filling a slot by exact or (when allowed) subsumed atom match."""
    eligible = [
        f
        for f in facts
        if (period_type is None or f.period_type == period_type)
        and (not require_unsegmented or not f.dimensions)
        and isinstance(f.value, (int, float))
    ]
    return [
        f
        for f in eligible
        if _atom_of(f.concept_qname) == slot.atom
        or (slot.accept_subsumed and _atom_of(f.concept_qname).is_a(slot.atom))
    ]


def _cleanest_value(matches: list[XbrlFact]) -> float | None:
    """Unique value among the fewest-residual matches, or None."""
    if not matches:
        return None
    min_residuals = min(_intent_residuals_of(f.concept_qname) for f in matches)
    cleanest = [
        f for f in matches if _intent_residuals_of(f.concept_qname) == min_residuals
    ]
    return _unique_value(cleanest)


def _slot_cleanest(
    facts: Sequence[XbrlFact],
    slot: _Slot,
    *,
    period_type: str | None = None,
    require_unsegmented: bool = True,
) -> list[XbrlFact]:
    """Cleanest facts filling a slot: exact/subsumed atom, fewest residuals."""
    matches = _slot_matches(
        facts, slot, period_type=period_type, require_unsegmented=require_unsegmented
    )
    if not matches:
        return []
    min_residuals = min(_intent_residuals_of(f.concept_qname) for f in matches)
    return [
        f for f in matches if _intent_residuals_of(f.concept_qname) == min_residuals
    ]


def _find_slot_value(
    facts: Sequence[XbrlFact],
    slot: _Slot,
    *,
    period_type: str | None = None,
    require_unsegmented: bool = True,
) -> float | None:
    """Find a fact filling an identity slot by atom coordinate matching."""
    matches = _slot_matches(
        facts, slot, period_type=period_type, require_unsegmented=require_unsegmented
    )
    return _cleanest_value(matches)


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


def verify_eps_identity(
    facts: Sequence[XbrlFact],
    tolerance: float | None = None,
    *,
    diluted: bool = False,
    scope: FactScope | None = None,
) -> IdentityVerification | None:
    """Verify EPS == income attributable to common / weighted-average shares.

    Tolerance is half the EPS fact's last printed digit (its decimals)
    unless given; a missing EPS, share, or numerator fact returns None.
    """
    selected = scope.select(list(facts)) if scope else facts
    eps_matches = _slot_cleanest(
        selected, _EPS_DILUTED if diluted else _EPS_BASIC, period_type="duration"
    )
    eps = _unique_value(eps_matches) if eps_matches else None
    shares = _find_slot_value(
        selected,
        _SHARES_DILUTED if diluted else _SHARES_BASIC,
        period_type="duration",
    )
    if eps is None or shares is None or shares == 0.0:
        return None
    numerator = None
    variant = "V_DILUTED" if diluted else "V_BASIC"
    for tier in _NUMERATOR_TIERS:
        matches = _slot_matches(selected, tier, period_type="duration")
        same_variant = [
            f for f in matches if variant in _atom_of(f.concept_qname).modifiers
        ]
        numerator = _cleanest_value(same_variant or matches)
        if numerator is not None:
            break
    if numerator is None:
        return None

    if tolerance is None:
        printed = {
            f.decimals
            for f in eps_matches
            if f.decimals is not None and f.decimals >= 0
        }
        tolerance = 0.5 * 10.0 ** -printed.pop() if len(printed) == 1 else 0.005
    rhs = numerator / shares
    diff = round(eps - rhs, 4)
    kind = "Diluted" if diluted else "Basic"
    return IdentityVerification(
        identity_name=f"ID_EPS_{kind.upper()}",
        formula=f"EarningsPerShare{kind} == IncomeAttributableToCommon / "
        f"WeightedAverageShares{kind}",
        lhs_value=round(eps, 4),
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

    for diluted in (False, True):
        eps = verify_eps_identity(selected, diluted=diluted)
        if eps is not None:
            results.append(eps)

    return tuple(results)
