"""Canonical SEC form phrase sequence dictionaries for text healing.

Rules are organized into compositional groups so form-family cover profiles
can select them instead of consuming one global list. The aggregate
:data:`SEC_COVER_PHRASE_RULES` is preserved for callers that explicitly need
the full annual rule set; the preprocessor consumes profile-selected tuples.
"""

from __future__ import annotations

from defs.sec_forms.cover.vocabulary import PUBLIC_FLOAT_PHRASES, SHARES_PHRASES
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

# 6. Shares Outstanding & Capital Stock (annual covers)
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

# 7. Aggregate Market Value & Public Float (annual covers)
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

# 8. Documents Incorporated by Reference (annual covers)
DOCUMENTS_INCORPORATED_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="documents_incorporated_reference",
        tokens=["documents", "incorporated", "by", "reference"],
        anchor=["incorporated by reference"],
    ),
]

# 9. Auditor Information (annual covers, 2021+)
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

# 10. Extended Transition & Emerging Growth (annual covers)
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

# Common rules shared by every cover-bearing profile (annual + quarterly).
COMMON_PHRASE_RULES: list[PhraseSequenceRule] = [
    *BANNER_RULES,
    *FORM_TITLE_RULES,
    *PERIOD_FILE_REGISTRANT_RULES,
    *CONTACT_CAPTION_RULES,
    *REGISTRATION_RULES,
]

# Annual-only rules. These must never apply to quarterly, current-report, or
# no-cover profiles.
ANNUAL_ADDITIONAL_PHRASE_RULES: list[PhraseSequenceRule] = [
    *SHARES_RULES,
    *PUBLIC_FLOAT_RULES,
    *DOCUMENTS_INCORPORATED_RULES,
    *AUDITOR_RULES,
    *EXTENDED_TRANSITION_RULES,
]

# Backwards-compatible aggregate for callers that explicitly want the full
# annual rule set. The preprocessor consumes profile-selected tuples instead.
SEC_COVER_PHRASE_RULES: list[PhraseSequenceRule] = [
    *COMMON_PHRASE_RULES,
    *ANNUAL_ADDITIONAL_PHRASE_RULES,
]

__all__ = [
    "ANNUAL_ADDITIONAL_PHRASE_RULES",
    "AUDITOR_RULES",
    "BANNER_RULES",
    "CONTACT_CAPTION_RULES",
    "DOCUMENTS_INCORPORATED_RULES",
    "EXTENDED_TRANSITION_RULES",
    "FORM_TITLE_RULES",
    "PERIOD_FILE_REGISTRANT_RULES",
    "PUBLIC_FLOAT_RULES",
    "REGISTRATION_RULES",
    "SEC_COVER_PHRASE_RULES",
    "SHARES_RULES",
]
