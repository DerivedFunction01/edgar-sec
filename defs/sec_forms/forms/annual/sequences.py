"""Phrase sequence healing rules specific to annual report cover pages."""

from __future__ import annotations

from defs.sec_forms.forms.annual.vocabulary import (
    PUBLIC_FLOAT_PHRASES,
    SHARES_PHRASES,
)
from defs.text import PhraseSequenceRule

# 1. Shares Outstanding & Capital Stock (annual covers)
SHARES_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="shares_outstanding_caption",
        tokens=SHARES_PHRASES[2].split(),
        anchor=["shares outstanding", "common stock"],
    ),
    PhraseSequenceRule(
        name="shares_common_stock_outstanding",
        tokens=SHARES_PHRASES[3].split(),
        anchor=["shares", "outstanding"],
    ),
]

# 2. Aggregate Market Value & Public Float (annual covers)
PUBLIC_FLOAT_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="aggregate_market_value",
        tokens=[
            *PUBLIC_FLOAT_PHRASES[1].split()[:5],
            ["voting", "non-voting"],
            "and",
            ["voting", "non-voting"],
            *PUBLIC_FLOAT_PHRASES[1].split()[8:],
        ],
        anchor=["aggregate market value", "non-affiliates"],
    ),
    PhraseSequenceRule(
        name="held_by_non_affiliates",
        tokens=["held", "by", "non-affiliates", "of", "the", "registrant"],
        anchor=["non-affiliates"],
    ),
]

# 3. Documents Incorporated by Reference (annual covers)
DOCUMENTS_INCORPORATED_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="documents_incorporated_reference",
        tokens=["documents", "incorporated", "by", "reference"],
        anchor=["incorporated by reference"],
    ),
]

# 4. Auditor Information (annual covers, 2021+)
AUDITOR_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="auditor_firm_id",
        tokens=["auditor", "firm", ["id", "identification", "number"]],
        anchor=["auditor"],
    ),
    PhraseSequenceRule(
        name="auditor_name_location",
        tokens=["auditor", ["name", "location"]],
        anchor=["auditor"],
    ),
]

# 5. Extended Transition & Emerging Growth (annual covers)
EXTENDED_TRANSITION_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="extended_transition_period",
        tokens=[
            "extended",
            "transition",
            "period",
            "for",
            "complying",
            "with",
            "any",
            "new",
            "or",
            "revised",
            "financial",
            "accounting",
            "standards",
        ],
        anchor=["extended transition", "accounting standards"],
    ),
]

ANNUAL_ADDITIONAL_PHRASE_RULES: list[PhraseSequenceRule] = [
    *SHARES_RULES,
    *PUBLIC_FLOAT_RULES,
    *DOCUMENTS_INCORPORATED_RULES,
    *AUDITOR_RULES,
    *EXTENDED_TRANSITION_RULES,
]

__all__ = [
    "ANNUAL_ADDITIONAL_PHRASE_RULES",
    "AUDITOR_RULES",
    "DOCUMENTS_INCORPORATED_RULES",
    "EXTENDED_TRANSITION_RULES",
    "PUBLIC_FLOAT_RULES",
    "SHARES_RULES",
]
