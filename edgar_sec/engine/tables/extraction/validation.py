"""Arithmetic identities over typed rows, priced as confirmation only.

Key rows match on normalized labels, first valued match in row order;
values are the cleaned first-column values at their cleaned signs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.normalize import normalize_label
from edgar_sec.engine.tables.extraction.registry import IDENTITIES_BY_FAMILY
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable

_ABS_TOLERANCE = 2.0
_REL_TOLERANCE = 0.005

_Matcher = Callable[[str], bool]


# Closure tolerance is the Step 3 pricing tolerance — max(2 units,
# 0.5% of the target) — in the table's own stated units.
def _close(computed: float, target: float) -> bool:
    return abs(computed - target) <= max(_ABS_TOLERANCE, _REL_TOLERANCE * abs(target))


@dataclass(frozen=True, slots=True)
class IdentityOutcome:
    """One identity's evaluation: the keys matched and whether it closed."""

    identity: str
    family: str
    closed: bool
    keys: tuple[tuple[str, float], ...]


def _first_value(table: TypedTable, matcher: _Matcher) -> float | None:
    for row in table.rows:
        if (
            matcher(normalize_label(row.label))
            and row.values
            and row.values[0] is not None
        ):
            return float(row.values[0])
    return None


def _contains(*needles: str) -> _Matcher:
    return lambda label: all(needle in label for needle in needles)


def _is_total_assets(label: str) -> bool:
    return label.startswith("total assets")


def _is_total_liabilities(label: str) -> bool:
    return label.startswith("total liabilities") and "and" not in label


def _is_total_equity(label: str) -> bool:
    return (
        label.startswith("total") and "equity" in label and "liabilities" not in label
    )


def _is_combined(label: str) -> bool:
    return label.startswith("total liabilities and")


def _is_change_in_cash(label: str) -> bool:
    return (
        "net increase" in label or "net decrease" in label or "net change" in label
    ) and "cash" in label


def _is_fx_effect(label: str) -> bool:
    return "exchange rate" in label and "cash" in label


_REVENUE_EXACT = {"net sales", "revenues", "revenue", "net revenue", "sales"}
_REVENUE_EXCLUDED = ("cost", "expense", "tax", "income", "loss", "per share")


def _is_revenue(label: str) -> bool:
    return (
        ("revenue" in label or "sales" in label)
        and ("total" in label or label in _REVENUE_EXACT)
        and not any(word in label for word in _REVENUE_EXCLUDED)
    )


def _is_cogs(label: str) -> bool:
    return label.startswith("cost of")


def _is_gross_profit(label: str) -> bool:
    return "gross profit" in label or "gross margin" in label


def _balance_sheet(table: TypedTable) -> IdentityOutcome | None:
    spec = IDENTITIES_BY_FAMILY["balance_sheet"]
    assets = _first_value(table, _is_total_assets)
    if assets is None:
        return None
    combined = _first_value(table, _is_combined)
    if combined is not None:
        keys = (("total_assets", assets), ("combined", combined))
        return IdentityOutcome(spec.name, spec.family, _close(combined, assets), keys)
    liabilities = _first_value(table, _is_total_liabilities)
    equity = _first_value(table, _is_total_equity)
    if liabilities is None or equity is None:
        return None
    keys = (
        ("total_assets", assets),
        ("total_liabilities", liabilities),
        ("total_equity", equity),
    )
    return IdentityOutcome(
        spec.name, spec.family, _close(liabilities + equity, assets), keys
    )


def _cash_flow(table: TypedTable) -> IdentityOutcome | None:
    spec = IDENTITIES_BY_FAMILY["cash_flow"]
    values = {
        "operating": _first_value(table, _contains("net cash", "operating activities")),
        "investing": _first_value(table, _contains("net cash", "investing activities")),
        "financing": _first_value(table, _contains("net cash", "financing activities")),
        "change": _first_value(table, _is_change_in_cash),
    }
    if any(value is None for value in values.values()):
        return None
    keys = tuple((name, float(value)) for name, value in values.items())
    total = values["operating"] + values["investing"] + values["financing"]
    if _close(total, values["change"]):
        return IdentityOutcome(spec.name, spec.family, True, keys)
    fx = _first_value(table, _is_fx_effect)
    if fx is None:
        return IdentityOutcome(spec.name, spec.family, False, keys)
    keys = keys + (("fx", fx),)
    return IdentityOutcome(
        spec.name, spec.family, _close(total + fx, values["change"]), keys
    )


def _income_leg1(table: TypedTable) -> IdentityOutcome | None:
    spec = IDENTITIES_BY_FAMILY["income_statement"]
    revenue = _first_value(table, _is_revenue)
    cogs = _first_value(table, _is_cogs)
    gross = _first_value(table, _is_gross_profit)
    if revenue is None or cogs is None or gross is None:
        return None
    keys = (
        ("gross_profit", gross),
        ("revenue", revenue),
        ("cogs", cogs),
    )
    return IdentityOutcome(spec.name, spec.family, _close(revenue - cogs, gross), keys)


_EVALUATORS = (_balance_sheet, _cash_flow, _income_leg1)


def evaluate_math(table: TypedTable) -> tuple[IdentityOutcome, ...]:
    """Evaluate every priced identity; only evaluable ones return."""
    outcomes = []
    for evaluator in _EVALUATORS:
        outcome = evaluator(table)
        if outcome is not None:
            outcomes.append(outcome)
    return tuple(outcomes)
