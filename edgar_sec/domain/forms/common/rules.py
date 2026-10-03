"""Universal SEC form phrase sequence rules for cover-page text healing.

Contains common phrase-sequence rules shared across all cover-bearing SEC form
families (10-K, 10-Q, 20-F). Form-specific rules are defined in their respective
family packages (such as annual/sequences.py).

A token slot is matched against an alphanumeric-stripped, anchored whole-word
pattern, so a token carrying trailing punctuation (`"no."`, `"number,"`,
`"12(b)"`) can never match: the strip removes the punctuation and the anchored
pattern keeps it escaped. Every slot below therefore offers at least one
punctuation-free branch.
"""

from __future__ import annotations

from edgar_sec.foundation.text.healing import PhraseSequenceRule

# 1. Government & SEC Banners
BANNER_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="united_states_sec",
        tokens=["united", "states", "securities", "and", "exchange", "commission"],
        anchor=["united", "securities", "commission"],
    ),
    PhraseSequenceRule(
        name="washington_dc_zip",
        tokens=["washington", ["dc", "d.c."], r"\d{5}"],
        anchor=["washington"],
    ),
]

# 2. Form & Report Titles
FORM_TITLE_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="report_pursuant_act",
        tokens=[
            ["annual", "transition", "quarterly"],
            "report",
            "pursuant",
            "to",
            "section",
            ["13", "15d", "15(d)"],
            "of",
            "the",
            "securities",
            "exchange",
            "act",
            "of",
            "1934",
        ],
        anchor=["annual", "transition", "quarterly", "pursuant", "1934"],
    ),
    PhraseSequenceRule(
        name="mark_one",
        tokens=["mark", "one"],
        anchor=["mark"],
    ),
]

# 3. Period, File Number & Registrant Name
PERIOD_FILE_REGISTRANT_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="fiscal_year_ended",
        tokens=[
            "for",
            "the",
            ["fiscal", "transition", "quarterly"],
            ["year", "period"],
            ["ended", "from", "ending", "end"],
        ],
        anchor=["fiscal", "transition", "quarterly", "ended", "ending", "end"],
    ),
    PhraseSequenceRule(
        name="commission_file_number",
        tokens=["commission", "file", "number"],
        anchor=["commission"],
    ),
    PhraseSequenceRule(
        name="exact_name_registrant",
        tokens=[
            "exact",
            "name",
            "of",
            ["registrant", "registrant:", "issuer"],
            "as",
            "specified",
            "in",
            "its",
            "charter",
        ],
        anchor=["specified", "charter"],
    ),
]

# 4. Jurisdiction & IRS EIN
JURISDICTION_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="state_of_incorporation",
        tokens=[
            "state",
            "or",
            "other",
            "jurisdiction",
            "of",
            ["incorporation", "incorporation:", "organization"],
        ],
        anchor=["jurisdiction"],
    ),
    PhraseSequenceRule(
        name="irs_employer_id",
        tokens=[
            ["i.r.s.", "irs"],
            "employer",
            ["identification", "identification:"],
            ["no", "number", "num", "no."],
        ],
        anchor=["employer", "identification"],
    ),
]

# 5. Address & Telephone
ADDRESS_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="principal_executive_offices",
        tokens=["address", "of", "principal", "executive", "offices"],
        anchor=["principal", "executive", "offices"],
    ),
    PhraseSequenceRule(
        name="telephone_number",
        tokens=[
            ["registrant's", "issuer's", "registrant", "issuer"],
            "telephone",
            "number",
            "including",
            "area",
            "code",
        ],
        anchor=["telephone", "area", "code"],
    ),
]

# 6. Statutory Securities & Exchange
SECURITIES_EXCHANGE_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="securities_registered_12b",
        tokens=[
            "securities",
            "registered",
            "pursuant",
            "to",
            "section",
            ["12(b)", "12(b):"],
            "of",
            "the",
            "act:",
        ],
        anchor=["securities", "registered", "12(b)"],
    ),
    PhraseSequenceRule(
        name="securities_registered_12g",
        tokens=[
            "securities",
            "registered",
            "pursuant",
            "to",
            "section",
            ["12(g)", "12(g):"],
            "of",
            "the",
            "act:",
        ],
        anchor=["securities", "registered", "12(g)"],
    ),
    PhraseSequenceRule(
        name="trading_symbol_header",
        tokens=["trading", ["symbol", "symbol(s)"]],
        anchor=["trading"],
    ),
    PhraseSequenceRule(
        name="title_of_each_class",
        tokens=["title", "of", "each", "class"],
        anchor=["class"],
    ),
    PhraseSequenceRule(
        name="name_of_each_exchange",
        tokens=["name", "of", "each", "exchange", "on", "which", "registered"],
        anchor=["exchange", "registered"],
    ),
]

# 7. Shares Outstanding Rules (Shared across 10-K and 10-Q)
COMMON_SHARES_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="shares_outstanding_caption",
        tokens=[
            "indicate",
            "the",
            "number",
            "of",
            "shares",
            "outstanding",
            "of",
            "each",
            "of",
            "the",
            ["registrant's", "issuer's", "registrant", "issuer"],
            "classes",
            "of",
            "common",
            ["stock", "equity"],
            "as",
            "of",
        ],
        anchor=["shares outstanding", "common stock"],
    ),
    PhraseSequenceRule(
        name="shares_common_stock_outstanding",
        tokens=[
            "number",
            "of",
            "shares",
            "of",
            "common",
            ["stock", "equity"],
            "outstanding",
        ],
        anchor=["shares", "outstanding"],
    ),
]

# Roll-up of the cover-page tables above; not an independent rule set.
COMMON_PHRASE_RULES: list[PhraseSequenceRule] = [
    *BANNER_RULES,
    *FORM_TITLE_RULES,
    *PERIOD_FILE_REGISTRANT_RULES,
    *JURISDICTION_RULES,
    *ADDRESS_RULES,
    *SECURITIES_EXCHANGE_RULES,
]

__all__ = [
    "ADDRESS_RULES",
    "BANNER_RULES",
    "COMMON_PHRASE_RULES",
    "COMMON_SHARES_RULES",
    "FORM_TITLE_RULES",
    "JURISDICTION_RULES",
    "PERIOD_FILE_REGISTRANT_RULES",
    "SECURITIES_EXCHANGE_RULES",
]
