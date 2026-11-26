"""Precision veto compositions: the priced data.

The priced packet legs per family, the channel token
stoplist of the pricing standard, and the derived core
vocabularies carried as population constants.
"""

from __future__ import annotations

DERIV_FAMILY = "derivatives_hedging"

# DERIV-1 leg names, in the order the gate note reports them.
LEG_LEAD_CONVERTIBLE = "lead:convertible"
LEG_HEADER_SECURITIES = "hdr:securities"
LEG_STUB_CREDIT = "stub:credit"
LEG_HEADER_LEVEL = "hdr:level"

DERIV_LEAD_TOKEN = "convertible"
DERIV_HEADER_SECURITIES_TOKEN = "securities"
DERIV_STUB_TOKEN = "credit"
DERIV_HEADER_LEVEL_TOKEN = "level"

DT_FAMILY = "deferred_tax"

# DT-1 leg names, in the order the gate note reports them.
LEG_PCT_ROWS = "pct-rows"
LEG_EPS_HOST_ABSENT = "host-absent:eps_reconciliation"
LEG_STUB_BIGRAM = "bigram:income taxes"

DT_STUB_BIGRAM = "income taxes"
DT_VALUATION_ALLOWANCE_BIGRAM = "valuation allowance"

# DT-2 leg names (packet DT-COMBO): the composition condition
# and the priced form tests over the enlarged set.
LEG_DT_NONCOMPOSITION = "form:noncomposition"
LEG_DT_TOTALS_ONLY = "form:totals-only"
LEG_DT_PPA_FORM = "form:purchase-allocation"
LEG_DT_PROVISION_FORM = "form:provision"
LEG_DT_UTB_SUBJECT = "form:utb-subject"
LEG_DT_NO_SUBJECT = "form:no-dt-subject"
LEG_DT_SCHEDULE_II = "form:schedule-ii"

# DT-2 form phrases, read over normalized stub/header text.
DT_PPA_PHRASES = (
    "purchase price",
    "net tangible assets acquired",
    "consideration transferred",
)
DT_SCHEDULE_II_PHRASE = "deducted from assets"
DT_UTB_SUBJECT_PHRASE = "unrecognized income tax benefits"

# DT-S3X (packet DT-S3X): the subject as stated in lead prose, in
# either dialect, and the closing lines of a composition, read
# over normalized stub text.
DT_S3X_SUBJECT_PHRASES = ("deferred tax", "deferred income tax")
DT_S3X_COMPONENT_TERMS = (
    "net operating loss",
    "tax credit",
    "capital loss",
    "depreciation",
    "amortization",
    "deferred revenue",
    "accrued",
    "reserve",
    "compensation",
    "inventory",
    "basis difference",
    "partnership",
    "foreign",
    "state",
    "research",
    "lease",
    "allowance for",
    "unrealized",
    "hedg",
    "pension",
    "postretirement",
    "restructuring",
    "investment",
    "prepaid",
    "warrant",
    "convertible",
    "share-based",
    "stock compensation",
    "bad debt",
    "charitable",
    "interest expense",
    "deferred compensation",
    "employee benefit",
)
DT_S3X_CLOSING_PHRASES = (
    "total deferred tax",
    "net deferred tax",
    "valuation allowance",
    "total gross",
    "less valuation",
    "net deferred",
)



DEBT_FAMILY = "debt_maturity"

# DEBT-P9 leg name, as the gate note reports it: the claim's
# own-stage support is the leadin channel alone.
LEG_LEADIN_ONLY = "leadin-only"

# P9's priced bounds: the claim geometry's numeric-cell cap
# and the header-year window of the year→amount pair test.
DEBT_NUMERIC_CELLS_MAX = 12
DEBT_HEADER_YEAR_MIN = 1900
DEBT_HEADER_YEAR_MAX = 2100

# Derived core vocabulary of the eps_reconciliation host:
# stub tokens at >= 50% frequency over the family's Round-2
# member trues, carried verbatim as a population constant.
EPS_RECONCILIATION_CORE = frozenset(
    {
        "average",
        "basic",
        "common",
        "diluted",
        "dilutive",
        "income",
        "net",
        "options",
        "share",
        "shares",
        "stock",
        "weighted",
    }
)

EPS_FAMILY = "eps_reconciliation"

# EPS-P leg names, in the order the gate note reports them.
LEG_RESTATEMENT_FACE_STATEMENT = "restatement:face-statement"
LEG_CONTEXT_ONLY = "context-only"

# EPS-P1: the restatement-adjustment header token set — an
# adjustment token plus the restated/previously/reported
# tokens, read over the geometry's normalized headers.
EPS_ADJUSTMENT_TOKENS = ("adjustment", "adjustments")
EPS_RESTATEMENT_TOKENS = ("restated", "previously", "reported")

# EPS-P1: a face statement named in the header/stub text.
EPS_FACE_STATEMENT_PHRASES = (
    "statement of operations",
    "statements of operations",
    "balance sheet",
    "statement of cash flows",
    "statements of cash flows",
)

# EPS-P2: the channels that lend no own-text mass to a score.
EPS_NON_OWN_CHANNELS = ("context", "veto")

INV_FAMILY = "inventory"

# INV-1 leg names, in the order the gate note reports them.
# The packet ships its zero-claimed-touch composed form,
# which the build-base re-price held at P' 1.000.
LEG_CREDIT_LOSSES_HOST = "host:credit_losses_rollforward"
LEG_LEAD_TABLES = "lead:tables"
LEG_LEAD_INVENTORY = "lead:inventory"

INV_LEAD_TABLES_TOKEN = "tables"
INV_LEAD_INVENTORY_TOKEN = "inventory"

LABOR_FAMILY = "labor_contracts"

# Labor leg names, in the order the gate note reports them.
LEG_EMPLOYER_FORM = "hdr:employer-form"
LEG_CONTRIBUTIONS_ORPHAN = "hdr:contributions-no-expiration"

# The placement-refined caption leg: a contributions header
# whose geometry carries no expiration header (the priced
# genuine form carries the CBA expiration in-geometry).
LABOR_CONTRIBUTIONS_PHRASE = "contributions of"
LABOR_EXPIRATION_TOKEN = "expiration"

# The multiemployer-plan form signature, read over the
# geometry's normalized headers: an EIN token or the
# EIN/plan-number header form, or a form phrase.
LABOR_EIN_TOKEN = "ein"
LABOR_EIN_PREFIX = "ein/"
LABOR_FORM_PHRASES = ("pension protection act", "fip/rp", "zone status")

# Derived core vocabulary of the credit_losses_rollforward
# host, derived as the eps host's core above.
CREDIT_LOSSES_CORE = frozenset(
    {
        "balance",
        "beginning",
        "losses",
        "provision",
        "recoveries",
    }
)

CREDIT_FAMILY = "credit_losses_rollforward"

# Credit dominance leg name, as the gate note reports it.
LEG_DOMINANT_CO_CLAIM = "dom:co-claim"

# The priced dominance margin: a co-claimant family's
# total must clear the credit claim's total by at least
# this margin for the leg to refuse the credit claim.
CREDIT_DOMINANCE_MARGIN = 5.0

INT_FAMILY = "intangibles"
GOODWILL_FAMILY = "goodwill_rollforward"

# F1 leg name, in the order the gate note reports it.
LEG_GOODWILL_HOST = "host:goodwill_rollforward"

# The failed composition evidence detail the F1 leg reads:
# the recorded failure, never the absence of a pass.
INT_COMPOSITION_FAILED_DETAIL = "intangibles_composition failed"

# Header/caption function words stoplisted from the token
# pools by the imposter-census standard (v2 cure).
TOKEN_STOPLIST = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "were",
        "was",
        "are",
        "has",
        "have",
        "had",
        "its",
        "per",
        "ended",
        "ending",
        "period",
        "periods",
        "months",
        "month",
        "three",
        "six",
        "nine",
        "twelve",
        "year",
        "years",
        "date",
        "dates",
        "following",
        "table",
        "below",
        "above",
        "shown",
        "amounts",
        "amount",
        "dollars",
        "thousands",
        "millions",
        "unaudited",
        "audited",
        "notes",
        "note",
        "financial",
        "statements",
        "statement",
        "consolidated",
        "company",
        "inc",
        "llc",
        "corp",
        "these",
        "those",
        "there",
        "their",
        "which",
        "while",
        "such",
        "both",
        "each",
        "any",
        "all",
        "more",
        "most",
        "only",
        "over",
        "under",
        "after",
        "before",
        "during",
        "between",
        "through",
        "about",
        "into",
        "upon",
        "within",
        "without",
        "may",
        "will",
        "would",
        "could",
        "should",
        "shall",
        "can",
        "cannot",
        "also",
        "however",
        "including",
        "includes",
        "include",
        "related",
        "certain",
        "various",
        "respective",
        "respectively",
        "first",
    }
)
