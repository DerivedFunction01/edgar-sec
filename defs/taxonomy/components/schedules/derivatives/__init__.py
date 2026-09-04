"""Derivatives, hedging activities (ASC 815), and AOCI (ASC 220) taxonomy package."""

from __future__ import annotations

from defs.taxonomy.components.schedules.derivatives.aoci import (
    AOCI_PRIMARY_TERMS,
    AOCI_SECONDARY_TERMS,
)
from defs.taxonomy.components.schedules.derivatives.cp import COMMODITY_DERIVATIVE_TERMS
from defs.taxonomy.components.schedules.derivatives.credit import (
    CREDIT_DERIVATIVE_TERMS,
)
from defs.taxonomy.components.schedules.derivatives.eq import EQUITY_DERIVATIVE_TERMS
from defs.taxonomy.components.schedules.derivatives.fx import FX_DERIVATIVE_TERMS
from defs.taxonomy.components.schedules.derivatives.generic import (
    ASC_815_MASTER_DISCLOSURES,
    CROSS_ASSET_STRUCTURES,
    DERIVATIVE_HEADING_TERMS,
    GENERIC_DERIVATIVE_TERMS,
)
from defs.taxonomy.components.schedules.derivatives.guards import (
    NON_DERIVATIVE_EXCLUSIONS,
)
from defs.taxonomy.components.schedules.derivatives.ir import IR_DERIVATIVE_TERMS
from defs.taxonomy.components.schedules.derivatives.spec import (
    AOCI_SPEC,
    DERIVATIVES_CONTEXT_TERMS,
    DERIVATIVES_HEDGING_SPEC,
    DERIVATIVES_PRIMARY_TERMS,
    DERIVATIVES_VETOES,
)

__all__ = [
    "AOCI_PRIMARY_TERMS",
    "AOCI_SECONDARY_TERMS",
    "AOCI_SPEC",
    "ASC_815_MASTER_DISCLOSURES",
    "COMMODITY_DERIVATIVE_TERMS",
    "CREDIT_DERIVATIVE_TERMS",
    "CROSS_ASSET_STRUCTURES",
    "DERIVATIVES_CONTEXT_TERMS",
    "DERIVATIVES_HEDGING_SPEC",
    "DERIVATIVES_PRIMARY_TERMS",
    "DERIVATIVES_VETOES",
    "DERIVATIVE_HEADING_TERMS",
    "EQUITY_DERIVATIVE_TERMS",
    "FX_DERIVATIVE_TERMS",
    "GENERIC_DERIVATIVE_TERMS",
    "IR_DERIVATIVE_TERMS",
    "NON_DERIVATIVE_EXCLUSIONS",
]
