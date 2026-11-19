"""Income-statement set-level stage (stage S): spec data.

The priced constants the stage reads: the fresh core
vocabulary carried as data, the ties leg's anchor families.
"""

from __future__ import annotations

FAMILY = "income_statement"

# The priced fresh core vocabulary (the set-level pricing
# board's core_vocab_fresh): stub keys carried by at least
# max(2, 0.2 * n) of the fresh golds, carried as spec data.
CORE_VOCAB_FRESH: tuple[str, ...] = (
    "interest expense",
    "net income",
    "revenues",
    "operating expenses",
    "interest income",
    "total operating expenses",
    "cost of sales",
    "basic",
    "diluted",
    "income tax expense",
    "other",
    "gross profit",
    "income before income taxes",
)

# Anchor statement families for the ties leg: a filing
# geometry grouped under one of these families can anchor
# the income-statement claim's net values.
ANCHOR_FAMILIES: tuple[str, ...] = (
    "cash_flow",
    "equity_statement",
    "comprehensive_income",
    "combined_operations_ci",
)
