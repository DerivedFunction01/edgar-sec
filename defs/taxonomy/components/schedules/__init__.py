"""Statutory disclosure and schedule concepts."""

from __future__ import annotations

from .deferred_tax import DEFERRED_TAX_SPEC
from .derivatives import AOCI_SPEC, DERIVATIVES_HEDGING_SPEC
from .eps_reconciliation import EPS_RECONCILIATION_SPEC
from .exhibit_index import (
    CANONICAL_EXHIBIT_HEADERS,
    EXHIBIT_INDEX_SPEC,
    EXHIBIT_INDEX_STATUTORY_PHRASES,
)
from .fair_value import FAIR_VALUE_SPEC
from .intangibles import INTANGIBLES_SPEC
from .inventory import INVENTORY_SPEC
from .labor import LABOR_CONTRACTS_SPEC
from .lease_maturity import LEASE_MATURITY_SPEC
from .legal import LEGAL_ALL_TERMS
from .pension import PENSION_SPEC
from .ppe import PPE_SPEC
from .shares_purchased import (
    CANONICAL_REPURCHASE_HEADERS,
    SHARES_PURCHASED_SPEC,
    SHARES_PURCHASED_STATUTORY_PHRASES,
)
from .stock_comp import STOCK_COMP_ROLLFORWARD_SPEC
from .tax_reconciliation import TAX_RECONCILIATION_SPEC

__all__ = [
    "AOCI_SPEC",
    "CANONICAL_EXHIBIT_HEADERS",
    "CANONICAL_REPURCHASE_HEADERS",
    "DEFERRED_TAX_SPEC",
    "DERIVATIVES_HEDGING_SPEC",
    "EPS_RECONCILIATION_SPEC",
    "EXHIBIT_INDEX_SPEC",
    "EXHIBIT_INDEX_STATUTORY_PHRASES",
    "FAIR_VALUE_SPEC",
    "INTANGIBLES_SPEC",
    "INVENTORY_SPEC",
    "LABOR_CONTRACTS_SPEC",
    "LEASE_MATURITY_SPEC",
    "LEGAL_ALL_TERMS",
    "PENSION_SPEC",
    "PPE_SPEC",
    "SHARES_PURCHASED_SPEC",
    "SHARES_PURCHASED_STATUTORY_PHRASES",
    "STOCK_COMP_ROLLFORWARD_SPEC",
    "TAX_RECONCILIATION_SPEC",
]
