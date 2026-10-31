"""Master table family registry."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.components.cover import (
    CHECKBOX_GRID_SPEC,
    COVER_LAYOUT_SPEC,
    REGISTRATION_TABLE_SPEC,
)
from edgar_sec.domain.taxonomy.schedules.debt_maturity import DEBT_MATURITY_SPEC
from edgar_sec.domain.taxonomy.schedules.deferred_tax import DEFERRED_TAX_SPEC
from edgar_sec.domain.taxonomy.schedules.derivatives.spec import (
    AOCI_SPEC,
    DERIVATIVES_HEDGING_SPEC,
)
from edgar_sec.domain.taxonomy.schedules.eps_reconciliation import (
    EPS_RECONCILIATION_SPEC,
)
from edgar_sec.domain.taxonomy.schedules.fair_value import FAIR_VALUE_SPEC
from edgar_sec.domain.taxonomy.schedules.intangibles import INTANGIBLES_SPEC
from edgar_sec.domain.taxonomy.schedules.inventory import INVENTORY_SPEC
from edgar_sec.domain.taxonomy.schedules.labor import LABOR_CONTRACTS_SPEC
from edgar_sec.domain.taxonomy.schedules.lease_maturity import LEASE_MATURITY_SPEC
from edgar_sec.domain.taxonomy.schedules.pension import PENSION_SPEC
from edgar_sec.domain.taxonomy.schedules.ppe import PPE_SPEC
from edgar_sec.domain.taxonomy.schedules.shares_purchased import SHARES_PURCHASED_SPEC
from edgar_sec.domain.taxonomy.schedules.stock_comp import (
    STOCK_COMP_ROLLFORWARD_SPEC,
)
from edgar_sec.domain.taxonomy.schedules.tax_reconciliation import (
    TAX_RECONCILIATION_SPEC,
)
from edgar_sec.domain.taxonomy.statements.balance import BALANCE_SHEET_SPEC
from edgar_sec.domain.taxonomy.statements.cash_flow import CASH_FLOW_SPEC
from edgar_sec.domain.taxonomy.statements.equity import EQUITY_STATEMENT_SPEC
from edgar_sec.domain.taxonomy.statements.income import INCOME_STATEMENT_SPEC
from edgar_sec.domain.taxonomy.tables.specs import TableFamilySpec

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
