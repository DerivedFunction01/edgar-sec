"""Canonical SEC form phrase sequence dictionaries for text healing.

Contains common phrase-sequence rules shared across all cover-bearing SEC form
families. Form-specific rules (e.g. annual float, shares outstanding, auditor
information) are owned by their respective form modules (such as
:mod:`defs.sec_forms.forms.annual`).
"""

from __future__ import annotations

from defs.text import PhraseSequenceRule

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
        name="exact_name_charter",
        tokens=[
            "exact",
            "name",
            "of",
            "registrant",
            "as",
            "specified",
            "in",
            "its",
            "charter",
        ],
        anchor=["registrant", "charter"],
    ),
]

# 4. State, EIN, Address & Contact Captions
CONTACT_CAPTION_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="state_incorporation_caption",
        tokens=[
            "state",
            "or",
            "other",
            "jurisdiction",
            "of",
            "incorporation",
            "or",
            "organization",
        ],
        anchor=["incorporation", "organization", "jurisdiction"],
    ),
    PhraseSequenceRule(
        name="irs_ein_caption",
        tokens=[
            ["irs", "i.r.s.", "taxpayer"],
            "employer",
            "identification",
            ["no", "number", "num", "no."],
        ],
        anchor=["irs", "employer", "taxpayer"],
    ),
    PhraseSequenceRule(
        name="address_executive_caption",
        tokens=["address", "of", "principal", "executive", "offices"],
        anchor=["principal", "executive", "offices"],
    ),
    PhraseSequenceRule(
        name="telephone_caption",
        tokens=[
            ["registrant's", "registrant"],
            "telephone",
            "number",
            "including",
            "area",
            "code",
        ],
        anchor=["telephone", "area code"],
    ),
]

# 5. Section 12 Securities Captions (present on 10-K, 10-Q, 20-F covers)
REGISTRATION_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="securities_12b_caption",
        tokens=[
            "securities",
            "registered",
            "pursuant",
            "to",
            "section",
            ["12b", "12g", "12(b)", "12(g)"],
        ],
        anchor=["registered", "section 12"],
    ),
    PhraseSequenceRule(
        name="title_of_each_class",
        tokens=["title", "of", "each", "class"],
        anchor=["class"],
    ),
    PhraseSequenceRule(
        name="name_of_each_exchange",
        tokens=["name", "of", "each", "exchange", "on", "which", "registered"],
        anchor=["exchange"],
    ),
]

# Common rules shared by every cover-bearing profile (annual + quarterly).
COMMON_PHRASE_RULES: list[PhraseSequenceRule] = [
    *BANNER_RULES,
    *FORM_TITLE_RULES,
    *PERIOD_FILE_REGISTRANT_RULES,
    *CONTACT_CAPTION_RULES,
    *REGISTRATION_RULES,
]

# Alias for root exports
SEC_COVER_PHRASE_RULES: list[PhraseSequenceRule] = COMMON_PHRASE_RULES

__all__ = [
    "BANNER_RULES",
    "COMMON_PHRASE_RULES",
    "CONTACT_CAPTION_RULES",
    "FORM_TITLE_RULES",
    "PERIOD_FILE_REGISTRANT_RULES",
    "REGISTRATION_RULES",
    "SEC_COVER_PHRASE_RULES",
]
