"""Annual report (10-K, 20-F) definitions, taxonomy, vocabulary, and evidence."""

from __future__ import annotations

from defs.sec_forms.forms.annual.evidence import AnnualReportEvidence
from defs.sec_forms.forms.annual.sequences import (
    ANNUAL_ADDITIONAL_PHRASE_RULES,
    AUDITOR_RULES,
    DOCUMENTS_INCORPORATED_RULES,
    EXTENDED_TRANSITION_RULES,
    PUBLIC_FLOAT_RULES,
    SHARES_RULES,
)
from defs.sec_forms.forms.annual.taxonomy import ITEMS, PARTS
from defs.sec_forms.forms.annual.vocabulary import (
    INCORPORATED_REFERENCE_TERMS,
    PUBLIC_FLOAT_ANCHOR_RE,
    PUBLIC_FLOAT_EXACT_RE,
    PUBLIC_FLOAT_PHRASES,
    PUBLIC_FLOAT_VALUE_RE,
    SHARES_ANCHOR_RE,
    SHARES_PHRASES,
    SHARES_VALUE_RE,
)

__all__ = [
    "ANNUAL_ADDITIONAL_PHRASE_RULES",
    "AUDITOR_RULES",
    "DOCUMENTS_INCORPORATED_RULES",
    "EXTENDED_TRANSITION_RULES",
    "INCORPORATED_REFERENCE_TERMS",
    "ITEMS",
    "PARTS",
    "PUBLIC_FLOAT_ANCHOR_RE",
    "PUBLIC_FLOAT_EXACT_RE",
    "PUBLIC_FLOAT_PHRASES",
    "PUBLIC_FLOAT_RULES",
    "PUBLIC_FLOAT_VALUE_RE",
    "SHARES_ANCHOR_RE",
    "SHARES_PHRASES",
    "SHARES_RULES",
    "SHARES_VALUE_RE",
    "AnnualReportEvidence",
]
