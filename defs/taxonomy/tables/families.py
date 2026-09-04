"""Master table family registry."""

from __future__ import annotations

from defs.taxonomy.components.cover import (
    CHECKBOX_GRID_SPEC,
    COVER_LAYOUT_SPEC,
    REGISTRATION_TABLE_SPEC,
)
from defs.taxonomy.components.financials.balance import BALANCE_SHEET_SPEC
from defs.taxonomy.components.financials.cash_flow import CASH_FLOW_SPEC
from defs.taxonomy.components.financials.equity import EQUITY_STATEMENT_SPEC
from defs.taxonomy.components.financials.income import INCOME_STATEMENT_SPEC
from defs.taxonomy.components.schedules.debt_maturity import DEBT_MATURITY_SPEC
from defs.taxonomy.components.schedules.deferred_tax import DEFERRED_TAX_SPEC
from defs.taxonomy.components.schedules.derivatives import (
    AOCI_SPEC,
    DERIVATIVES_HEDGING_SPEC,
)
from defs.taxonomy.components.schedules.eps_reconciliation import (
    EPS_RECONCILIATION_SPEC,
)
from defs.taxonomy.components.schedules.fair_value import FAIR_VALUE_SPEC
from defs.taxonomy.components.schedules.intangibles import INTANGIBLES_SPEC
from defs.taxonomy.components.schedules.inventory import INVENTORY_SPEC
from defs.taxonomy.components.schedules.labor import LABOR_CONTRACTS_SPEC
from defs.taxonomy.components.schedules.lease_maturity import LEASE_MATURITY_SPEC
from defs.taxonomy.components.schedules.pension import PENSION_SPEC
from defs.taxonomy.components.schedules.ppe import PPE_SPEC
from defs.taxonomy.components.schedules.shares_purchased import SHARES_PURCHASED_SPEC
from defs.taxonomy.components.schedules.stock_comp import (
    STOCK_COMP_ROLLFORWARD_SPEC,
)
from defs.taxonomy.components.schedules.tax_reconciliation import (
    TAX_RECONCILIATION_SPEC,
)
from defs.taxonomy.tables.specs import TableFamilySpec

FAMILY_SPECS: dict[str, TableFamilySpec] = {
    spec.name: spec
    for spec in (
        COVER_LAYOUT_SPEC,
        CHECKBOX_GRID_SPEC,
        REGISTRATION_TABLE_SPEC,
        SHARES_PURCHASED_SPEC,
        INCOME_STATEMENT_SPEC,
        BALANCE_SHEET_SPEC,
        CASH_FLOW_SPEC,
        EQUITY_STATEMENT_SPEC,
        LEASE_MATURITY_SPEC,
        DEBT_MATURITY_SPEC,
        TAX_RECONCILIATION_SPEC,
        DEFERRED_TAX_SPEC,
        FAIR_VALUE_SPEC,
        STOCK_COMP_ROLLFORWARD_SPEC,
        PENSION_SPEC,
        EPS_RECONCILIATION_SPEC,
        LABOR_CONTRACTS_SPEC,
        INVENTORY_SPEC,
        PPE_SPEC,
        INTANGIBLES_SPEC,
        DERIVATIVES_HEDGING_SPEC,
        AOCI_SPEC,
    )
}

__all__ = ["FAMILY_SPECS", "TableFamilySpec"]
