"""Central false positive guards and fast-veto registries aggregating category-owned guards."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.schedules.derivatives.cp import (
    COMMODITY_PHYSICAL_SUPPLY_GUARDS,
)
from edgar_sec.domain.taxonomy.schedules.derivatives.eq import (
    EQUITY_EMPLOYEE_COMP_GUARDS,
    EQUITY_UNIGRAM_VETOES,
)
from edgar_sec.domain.taxonomy.schedules.derivatives.generic import (
    GENERIC_NON_FINANCIAL_PHRASES,
    GENERIC_UNIGRAM_VETOES,
)
from edgar_sec.domain.taxonomy.schedules.legal import (
    LEGAL_ALL_TERMS,
    LEGAL_UNIGRAM_VETOES,
)
from edgar_sec.foundation.text.compounds import expand_alternations

DERIVATIVE_UNIGRAM_VETOES: tuple[str, ...] = (
    *GENERIC_UNIGRAM_VETOES,
    *EQUITY_UNIGRAM_VETOES,
    *LEGAL_UNIGRAM_VETOES,
    "activities",  # Cash Flow Statement unigram veto
)


# Central multi-word phrase exclusions aggregating all category-owned noise
NON_DERIVATIVE_PHRASE_EXCLUSIONS: tuple[str, ...] = expand_alternations(
    COMMODITY_PHYSICAL_SUPPLY_GUARDS,
    EQUITY_EMPLOYEE_COMP_GUARDS,
    GENERIC_NON_FINANCIAL_PHRASES,
    LEGAL_ALL_TERMS,
)

NON_DERIVATIVE_EXCLUSIONS: tuple[str, ...] = DERIVATIVE_UNIGRAM_VETOES

__all__ = [
    "DERIVATIVE_UNIGRAM_VETOES",
    "NON_DERIVATIVE_EXCLUSIONS",
    "NON_DERIVATIVE_PHRASE_EXCLUSIONS",
]
