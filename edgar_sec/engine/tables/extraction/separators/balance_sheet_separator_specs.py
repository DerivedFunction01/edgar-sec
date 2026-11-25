"""Balance-sheet separator parameter table (TEST_BALANCE_SHEET_SEPARATOR).
The priced leg set as data: a composition over the imposter
census's best pair, priced over its balance_sheet population
(73 falses / 122 trues, touch budget 12, price 73/73 at 12).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BalanceSheetSeparatorLeg:
    """One priced separator leg: its feature kind and parameter.
    Kinds: rows (grid lines at most limit), years (header year tokens
    at least limit), header (key), stub (key), numshare (below limit)."""

    leg_id: str
    kind: str
    term: str = ""
    limit: float = 0.0


@dataclass(frozen=True)
class BalanceSheetSeparatorSpec:
    """One family's separator: the ordered legs plus leg 11.
    Leg 11 fires when any accrued-composition phrase is a stub
    key; it is the priced survivor addition, at 0 touches."""

    family: str
    legs: tuple[BalanceSheetSeparatorLeg, ...]
    accrued_stub_phrases: tuple[str, ...]
    # The closing-pair exemption: these legs stay silent when the
    # grid closes the balance-sheet identity (a total-assets stub,
    # a total-liabilities stub, and an equity-total stub key).
    closing_pair_exempt_legs: tuple[str, ...] = ()
    equity_total_keys: tuple[str, ...] = ()


BALANCE_SHEET_SEPARATOR_SPECS = {
    "balance_sheet": BalanceSheetSeparatorSpec(
        family="balance_sheet",
        legs=(
            BalanceSheetSeparatorLeg("year_ladder", "years", limit=3),
            BalanceSheetSeparatorLeg("hdr:fair", "header", "fair"),
            BalanceSheetSeparatorLeg("hdr:sheet", "header", "sheet"),
            BalanceSheetSeparatorLeg(
                "stub:total common equity", "stub", "total common equity"
            ),
            BalanceSheetSeparatorLeg(
                "stub:total other non current liabilities",
                "stub",
                "total other non current liabilities",
            ),
            BalanceSheetSeparatorLeg("hdr:issuer", "header", "issuer"),
            BalanceSheetSeparatorLeg("hdr:funds", "header", "funds"),
            BalanceSheetSeparatorLeg(
                "stub:noncurrent assets", "stub", "noncurrent assets"
            ),
            BalanceSheetSeparatorLeg("numshare_lt_0.3", "numshare", limit=0.3),
        ),
        accrued_stub_phrases=(
            "accrued research and development expenses",
            "accrued professional services",
            "accrued construction costs",
            "total accrued liabilities",
        ),
        closing_pair_exempt_legs=(
            "hdr:issuer",
            "stub:noncurrent assets",
            "stub:total common equity",
        ),
        equity_total_keys=(
            "total equity",
            "total common equity",
            "total stockholders equity",
            "total shareholders equity",
            "total stockholders deficit",
            "total shareholders deficit",
            "total members equity",
            "total partners capital",
            "total capital",
        ),
    ),
}
