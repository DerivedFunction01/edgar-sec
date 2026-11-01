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

ITEM5_13G_INSTRUCTION_PATTERNS = (
    r"if\s+this\s+statement\s+is\s+being\s+filed\s+to\s+report\s+the\s+fact\s+that\s+as\s+of\s+the\s+date\s+hereof\s+the\s+reporting\s+person\s+has\s+ceased\s+to\s+be\s+the\s+beneficial\s+owner\s+of\s+more\s+than\s+(?:5|five)\s+percent\s+of\s+the\s+class\s+of\s+securities,?\s*check\s+the\s+following",
    r"check\s+the\s+following\s+if\s+the\s+reporting\s+person\s+has\s+ceased\s+to\s+be\s+the\s+beneficial\s+owner\s+of\s+more\s+than\s+(?:5|five)\s+percent",
)
ITEM6_13G_INSTRUCTION_PATTERNS = (
    r"if\s+any\s+other\s+person\s+is\s+known\s+to\s+have\s+the\s+right\s+to\s+receive\s+or\s+the\s+power\s+to\s+direct\s+the\s+receipt\s+of\s+dividends\s+from,?\s*or\s+the\s+proceeds\s+from\s+the\s+sale\s+of,?\s*such\s+securities,?\s*a\s+statement\s+to\s+that\s+effect\s+should\s+be\s+included.*?(?:is\s+not\s+required\.?|$)",
)
ITEM7_13G_INSTRUCTION_PATTERNS = (
    r"if\s+a\s+parent\s+holding\s+company\s+or\s+control\s+person\s+has\s+filed\s+this\s+schedule\s+pursuant\s+to\s+Rule\s+13d-1\(b\)\(1\)\(ii\)\(G\),?\s*so\s+indicate\s+under\s+Item\s+3\(g\)\s+and\s+attach\s+an\s+exhibit.*?(?:See\s+Item\s+5\.?|$)",
    r"see\s+Item\s+7\s+instructions.*?(?:\.|$)",
)
ITEM8_13G_INSTRUCTION_PATTERNS = (
    r"if\s+a\s+group\s+has\s+filed\s+this\s+schedule\s+pursuant\s+to\s+(?:Rule|§\s*240\.)13d-1\(b\)\(1\)\(ii\)\(J\),?\s*so\s+indicate\s+under\s+Item\s+3\(j\)\s+and\s+attach\s+an\s+exhibit.*?(?:each\s+member\s+of\s+the\s+group\.?|$)",
)
ITEM9_13G_INSTRUCTION_PATTERNS = (
    r"notice\s+of\s+dissolution\s+of\s+a\s+group\s+may\s+be\s+furnished\s+on\s+an\s+exhibit\s+stating\s+the\s+date\s+of\s+the\s+dissolution.*?(?:individual\s+capacity\.?\s*See\s+Item\s+5\.?|$)",
)

STATUTORY_ISSUER_NAME_LABELS = ("NAME OF ISSUER", "ISSUER NAME", "NAME OF THE ISSUER")
STATUTORY_ISSUER_ADDRESS_LABELS = (
    "ADDRESS OF ISSUER'S PRINCIPAL EXECUTIVE OFFICES",
    "ADDRESS OF ISSUERS PRINCIPAL EXECUTIVE OFFICES",
    "NAME OF ISSUER'S PRINCIPAL EXECUTIVE OFFICES",
    "NAME OF ISSUERS PRINCIPAL EXECUTIVE OFFICES",
    "ADDRESS OF PRINCIPAL EXECUTIVE OFFICES",
    "PRINCIPAL EXECUTIVE OFFICES",
)
STATUTORY_PERSON_NAME_LABELS = (
    "NAME OF PERSON FILING",
    "NAMES OF PERSONS FILING",
    "NAME OF REPORTING PERSON",
    "NAMES OF REPORTING PERSONS",
    "PERSON FILING",
    "NAME OF PERSON",
)
STATUTORY_PERSON_ADDRESS_LABELS = (
    "ADDRESS OF PRINCIPAL BUSINESS OFFICE OR, IF NONE, RESIDENCE",
    "ADDRESS OF PRINCIPAL BUSINESS OFFICE OR IF NONE RESIDENCE",
    "ADDRESS OF PRINCIPAL BUSINESS OFFICE",
    "PRINCIPAL BUSINESS OFFICE",
    "RESIDENCE ADDRESS",
)
STATUTORY_BUSINESS_LABELS = (
    "PRESENT PRINCIPAL OCCUPATION OR EMPLOYMENT",
    "PRINCIPAL OCCUPATION OR EMPLOYMENT",
    "PRINCIPAL OCCUPATION",
    "PRINCIPAL BUSINESS",
)
STATUTORY_CITIZENSHIP_LABELS = (
    "CITIZENSHIP OR PLACE OF ORGANIZATION",
    "PLACE OF ORGANIZATION",
    "CITIZENSHIP",
)
STATUTORY_SECURITY_CLASS_LABELS = (
    "TITLE OF CLASS OF SECURITIES",
    "CLASS OF SECURITIES",
)
STATUTORY_CUSIP_LABELS = ("CUSIP NUMBER", "CUSIP NO", "CUSIP")
STATUTORY_AMOUNT_OWNED_LABELS = (
    "AGGREGATE AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON",
    "AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON",
    "AGGREGATE AMOUNT BENEFICIALLY OWNED",
    "AMOUNT BENEFICIALLY OWNED",
)
STATUTORY_PERCENT_CLASS_LABELS = (
    "PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW",
    "PERCENT OF CLASS REPRESENTED BY AMOUNT",
    "PERCENT OF CLASS",
)
STATUTORY_POWER_GROUP_LABELS = (
    "NUMBER OF SHARES AS TO WHICH SUCH PERSON HAS",
    "NUMBER OF SHARES AS TO WHICH THE PERSON HAS",
    "NUMBER OF SHARES BENEFICIALLY OWNED BY EACH",
    "NUMBER OF SHARES BENEFICIALLY OWNED",
    "DEEMED VOTING POWER AND DISPOSITION POWER",
    "NUMBER OF SHARES",
)
STATUTORY_SOLE_VOTING_LABELS = (
    "SOLE POWER TO VOTE OR TO DIRECT THE VOTE",
    "SOLE POWER TO VOTE OR DIRECT THE VOTE",
    "SOLE POWER TO VOTE",
)
STATUTORY_SHARED_VOTING_LABELS = (
    "SHARED POWER TO VOTE OR TO DIRECT THE VOTE",
    "SHARED POWER TO VOTE OR DIRECT THE VOTE",
    "SHARED POWER TO VOTE",
)
STATUTORY_SOLE_DISPOSITIVE_LABELS = (
    "SOLE POWER TO DISPOSE OR TO DIRECT THE DISPOSITION OF",
    "SOLE POWER TO DISPOSE OR DIRECT THE DISPOSITION OF",
    "SOLE POWER TO DISPOSE",
)
STATUTORY_SHARED_DISPOSITIVE_LABELS = (
    "SHARED POWER TO DISPOSE OR TO DIRECT THE DISPOSITION OF",
    "SHARED POWER TO DISPOSE OR DIRECT THE DISPOSITION OF",
    "SHARED POWER TO DISPOSE",
)
STATUTORY_ITEM6_LABELS = (
    "OWNERSHIP OF MORE THAN FIVE PERCENT ON BEHALF OF ANOTHER PERSON",
    "OWNERSHIP OF MORE THAN 5% ON BEHALF OF ANOTHER PERSON",
    "MORE THAN FIVE PERCENT ON BEHALF OF ANOTHER PERSON",
    "MORE THAN 5% ON BEHALF OF ANOTHER PERSON",
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
    "ITEM5_13G_INSTRUCTION_PATTERNS",
    "ITEM6_13G_INSTRUCTION_PATTERNS",
    "ITEM7_13G_INSTRUCTION_PATTERNS",
    "ITEM8_13G_INSTRUCTION_PATTERNS",
    "ITEM9_13G_INSTRUCTION_PATTERNS",
    "PARSED_FIELD_BOILERPLATE_PHRASES",
    "STATUTORY_AMOUNT_OWNED_LABELS",
    "STATUTORY_BUSINESS_LABELS",
    "STATUTORY_CITIZENSHIP_LABELS",
    "STATUTORY_CUSIP_LABELS",
    "STATUTORY_ISSUER_ADDRESS_LABELS",
    "STATUTORY_ISSUER_NAME_LABELS",
    "STATUTORY_ITEM6_LABELS",
    "STATUTORY_PERCENT_CLASS_LABELS",
    "STATUTORY_PERSON_ADDRESS_LABELS",
    "STATUTORY_PERSON_NAME_LABELS",
    "STATUTORY_POWER_GROUP_LABELS",
    "STATUTORY_SECURITY_CLASS_LABELS",
    "STATUTORY_SHARED_DISPOSITIVE_LABELS",
    "STATUTORY_SHARED_VOTING_LABELS",
    "STATUTORY_SOLE_DISPOSITIVE_LABELS",
    "STATUTORY_SOLE_VOTING_LABELS",
]
