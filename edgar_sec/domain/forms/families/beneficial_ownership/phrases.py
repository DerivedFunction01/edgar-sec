from __future__ import annotations

from edgar_sec.domain.forms.common.phrases import (
    PhraseCategory,
    PhraseEffect,
    PhraseRule,
)

COVER_LABEL_LEAK_PHRASES = (
    "name of reporting person",
    "names of reporting persons",
    "check the appropriate box",
    "source of funds",
    "sec use only",
    "check if disclosure of legal proceedings",
    "citizenship or place of organization",
    "sole voting power",
    "shared voting power",
    "sole dispositive power",
    "shared dispositive power",
    "aggregate amount beneficially owned",
    "owned by",
    "owned by each reporting person",
    "person with",
    "identification nos. of above persons",
    "i.d. no.",
    "percent of class represented",
    "type of reporting person",
    "see instructions",
    "pursuant to items",
    "by each person",
    "voting power",
    "dispositive power",
    "shares beneficially owned",
)

PARSED_FIELD_BOILERPLATE_PHRASES = (
    "I.R.S. IDENTIFICATION",
    "CHECK THE APPROPRIATE BOX",
    "CHECK APPROPRIATE BOX",
    "TYPE OF REPORTING PERSON",
    "SCHEDULE 13D",
    "SCHEDULE 13G",
    "SECURITIES AND EXCHANGE COMMISSION",
    "UNDER THE SECURITIES EXCHANGE ACT",
    "SEE INSTRUCTIONS",
    "SIGNATURE",
    "ITEM 1.",
    "ITEM 2.",
    "ITEM 3.",
    "ITEM 4.",
    "ITEM 5.",
    "ITEM 6.",
    "ITEM 7.",
    "PERSONS WHO ARE TO RESPOND",
    "COLLECTION OF INFORMATION",
)

BENEFICIAL_OWNERSHIP_PHRASE_RULES = (
    PhraseRule(
        "beneficial_ownership.cover_label_leak",
        tuple((phrase,) for phrase in COVER_LABEL_LEAK_PHRASES),
        PhraseCategory.FIELD_LABEL,
        effect=PhraseEffect.EXCLUDE_FROM_VALUE,
        family_ids=frozenset({"beneficial_ownership"}),
    ),
    PhraseRule(
        "beneficial_ownership.parsed_field_boilerplate",
        tuple((phrase,) for phrase in PARSED_FIELD_BOILERPLATE_PHRASES),
        PhraseCategory.BOILERPLATE,
        effect=PhraseEffect.EXCLUDE_FROM_VALUE,
        family_ids=frozenset({"beneficial_ownership"}),
    ),
)

__all__ = [
    "BENEFICIAL_OWNERSHIP_PHRASE_RULES",
    "COVER_LABEL_LEAK_PHRASES",
    "PARSED_FIELD_BOILERPLATE_PHRASES",
]
