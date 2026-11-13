"""Domain vocabulary and location expectations, injected by callers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Anchor:
    """A family title phrase matched in caption or heading text."""

    family: str
    phrases: tuple[str, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LabelRule:
    """A conjunction over normalized row labels; every group must hold."""

    family: str
    required: tuple[str, ...] = ()
    together: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassificationPolicy:
    """The injected vocabulary: specific winners and location priors."""

    specific: tuple[Anchor | LabelRule, ...] = ()
    location_priors: tuple[tuple[str, str | None, float], ...] = ()

    def location_share(self, family: str, item: str | None) -> float | None:
        """The prior share for a family in an Item, or None when unset."""
        for prior_family, prior_item, share in self.location_priors:
            if prior_family == family and prior_item == item:
                return share
        return None


def default_policy() -> ClassificationPolicy:
    """The seed policy: title anchoring generalized from `_table_roles`."""
    return ClassificationPolicy(
        specific=(
            LabelRule("eps_reconciliation", required=("for basic", "for diluted")),
            Anchor(
                "eps_reconciliation",
                ("earnings per share", "income per share"),
                ("caption", "heading"),
            ),
            Anchor("fair_value", ("fair value",), ("caption", "heading")),
            LabelRule(
                "deferred_tax",
                required=("deferred tax assets", "deferred tax liabilities"),
            ),
            LabelRule(
                "deferred_tax",
                together=("deferred", "tax"),
                any_of=("valuation allowance", "carryforward"),
            ),
            LabelRule("tax_reconciliation", required=("local taxes", "statutory tax")),
            Anchor(
                "equity_statement",
                (
                    "statements of equity",
                    "statement of equity",
                    "statements of changes in equity",
                    "changes in shareholders' equity",
                    "changes in stockholders' equity",
                ),
                ("caption", "heading"),
            ),
            LabelRule("inventory", required=("total inventory",)),
            LabelRule(
                "lease_maturity",
                any_of=("less: imputed interest", "total lease payments"),
            ),
            Anchor(
                "income_statement",
                (
                    "statements of income",
                    "statement of income",
                    "statements of operations",
                    "statement of operations",
                ),
                ("caption",),
            ),
            Anchor("balance_sheet", ("balance sheet",), ("caption",)),
            Anchor("cash_flow", ("cash flow",), ("caption",)),
        ),
    )
