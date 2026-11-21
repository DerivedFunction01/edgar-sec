"""Primary-statement seat specs, keyed by family."""

from __future__ import annotations

from dataclasses import dataclass


# The primary-statement seat (class iv): a statement table
# sits in the body region, outside the TOC and closing spans —
# the seat facts the context production carries.
SEAT_REGION_BODY = "body"


@dataclass(frozen=True, slots=True)
class SeatTestSpec:
    """One primary-statement seat test, declared as registry data.

    The seat facts must hold on the context, and the named
    identity must close over the table's own total rows.
    """

    identity: str
    required_roles: tuple[str, ...]
    ordered_roles: tuple[str, ...] = ()
    either_roles: tuple[tuple[str, ...], ...] = ()
    optional_roles: tuple[str, ...] = ()
    seat_region: str = SEAT_REGION_BODY
    in_toc_span: bool = False
    in_closing_span: bool = False
    tolerance_abs: float = 2.0
    tolerance_rel: float = 0.005


# Primary-statement seat specs (class (iv)), keyed by family:
# the one literal home of the seat kind's parameters.
SEAT_TEST_SPECS_BY_FAMILY: dict[str, SeatTestSpec] = {
    "balance_sheet": SeatTestSpec(
        identity="balance_sheet_either_form",
        required_roles=("total_assets",),
        either_roles=(("total_liabilities", "total_equity"), ("combined",)),
    ),
    "cash_flow": SeatTestSpec(
        identity="cash_flow_with_fx_leg",
        required_roles=("operating", "investing", "financing", "change"),
        ordered_roles=("operating", "investing", "financing", "change"),
        optional_roles=("fx", "cash_beginning", "cash_ending"),
    ),
    "equity_statement": SeatTestSpec(
        identity="equity_column_walk",
        required_roles=(
            "beginning_balance",
            "movement",
            "ending_balance",
            "component_columns",
            "total_column",
        ),
        ordered_roles=("beginning_balance", "ending_balance"),
    ),
    "income_statement": SeatTestSpec(
        identity="revenue_to_net_income_descent",
        required_roles=("revenue", "cogs", "gross_profit", "net_income"),
        ordered_roles=(
            "revenue",
            "cogs",
            "gross_profit",
            "operating_income",
            "pretax_income",
            "net_income",
        ),
        optional_roles=("operating_income", "pretax_income"),
    ),
}


def seat_test_spec_for(family: str) -> SeatTestSpec | None:
    """The family's primary-statement seat spec, or None."""
    return SEAT_TEST_SPECS_BY_FAMILY.get(family)
