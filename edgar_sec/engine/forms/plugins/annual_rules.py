"""Phrase sequence healing rules specific to annual report cover pages."""

from __future__ import annotations

from edgar_sec.foundation.text.healing import PhraseSequenceRule

# 1. Shares Outstanding & Capital Stock (annual covers)
_SHARES_PHRASE_REGISTRANT = (
    "indicate the number of shares outstanding of each of the "
    "registrant's classes of common stock as of"
)
_SHARES_PHRASE_ISSUER = (
    "indicate the number of shares outstanding of each of the "
    "issuer's classes of common stock as of"
)

SHARES_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="shares_outstanding_caption",
        tokens=_SHARES_PHRASE_REGISTRANT.split(),
        anchor=["shares outstanding", "common stock"],
    ),
    PhraseSequenceRule(
        name="shares_common_stock_outstanding",
        tokens=_SHARES_PHRASE_ISSUER.split(),
        anchor=["shares", "outstanding"],
    ),
]

# 2. Aggregate Market Value & Public Float (annual covers)
_PUBLIC_FLOAT_PHRASE_HEAD = ["the", "aggregate", "market", "value", "of"]
_PUBLIC_FLOAT_PHRASE_TAIL = [
    "common",
    "equity",
    "held",
    "by",
    "non-affiliates",
]

PUBLIC_FLOAT_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="aggregate_market_value",
        tokens=[
            *_PUBLIC_FLOAT_PHRASE_HEAD,
            ["voting", "non-voting"],
            "and",
            ["voting", "non-voting"],
            *_PUBLIC_FLOAT_PHRASE_TAIL,
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

ANNUAL_PHRASE_RULES: list[PhraseSequenceRule] = [
    *SHARES_RULES,
    *PUBLIC_FLOAT_RULES,
    *DOCUMENTS_INCORPORATED_RULES,
    *AUDITOR_RULES,
    *EXTENDED_TRANSITION_RULES,
]

__all__ = [
    "ANNUAL_PHRASE_RULES",
    "AUDITOR_RULES",
    "DOCUMENTS_INCORPORATED_RULES",
    "EXTENDED_TRANSITION_RULES",
    "PUBLIC_FLOAT_RULES",
    "SHARES_RULES",
]
