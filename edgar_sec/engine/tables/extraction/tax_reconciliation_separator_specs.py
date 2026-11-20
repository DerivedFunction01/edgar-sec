"""Tax reconciliation separator parameter table (TEST_TAX_RECONCILIATION_SEPARATOR).
The priced composition as built: the determined rate core absent,
conjoined with zero nonzero movement cells and a row bound
(provenance: PROV_TAX_RECONCILIATION_SEPARATOR).
"""

from dataclasses import dataclass

MOVE_WORDS = (
    "beginning",
    "ending",
    "granted",
    "exercised",
    "forfeited",
    "expired",
    "outstanding",
    "provision",
    "charge",
    "payment",
    "paid",
    "adjustment",
    "addition",
    "settlement",
    "incurred",
    "accrued",
    "deduction",
    "vested",
)


@dataclass(frozen=True)
class TaxReconciliationSeparatorSpec:
    """One family's separator: the priced conjunction's row bound.
    The refusal fires only when every leg holds: the rate core is
    absent, no movement line carries a nonzero value, and the grid
    has at most max_rows rows."""

    family: str
    max_rows: int


TAX_RECONCILIATION_SEPARATOR_SPECS = {
    "tax_reconciliation": TaxReconciliationSeparatorSpec(
        family="tax_reconciliation",
        max_rows=8,
    ),
}
