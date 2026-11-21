"""Step 8 core-form parameter tables (TEST_CORE_FORM).
The definition set as data, re-derived from gold-side evidence as a
new pricing act (provenance: PROV_STEP8_PRICING). Gold-ambiguous and
gold-unexercised choices are flagged inline as named suspects.
"""

from dataclasses import dataclass, field

# Intangibles class lexicon: nclass counts distinct terms matched as
# substrings of normalized stub text. 14 terms are gold-exercised;
# the last 3 are gold-unexercised flagged choices, in order.
INTANGIBLES_LEXICON = (
    "customer relationships",
    "trade names",
    "core technology",
    "patents",
    "licenses",
    "product lines",
    "non-compete",
    "order backlog",
    "internal-use software",
    "existing technology",
    "developed technology",
    "trademarks",
    "customer list",
    "debt offering costs",
    "in-process research and development",  # gold-unexercised
    "copyrights",  # gold-unexercised
    "franchise rights",  # gold-unexercised
)

# Segment col stoplist, matched against the cell's base form
# (trailing parentheticals stripped); the four marked measure words
# are gold-ambiguous picks from an 8-candidate ambiguous set.
SEGMENT_COL_STOPLIST = frozenset(
    {
        "total",
        "net sales",
        "net earnings",
        "ended",
        "(unaudited)",
        "of total",
        "ebit",
        "% of total",
        "net income",
        "total assets",
        "operating income",
        "income",
        "total revenue",
        "inter-",
        "not topic",
        "protection",
        "amortization",  # gold-ambiguous pick
        "assets",  # gold-ambiguous pick
        "capital",  # gold-ambiguous pick
        "depreciation",  # gold-ambiguous pick
    }
)

# Segment stub stoplist, matched against the stub's base form;
# 'operating loss' is a gold-ambiguous pick (1 of 3 consistent
# candidates for one gold).
SEGMENT_STUB_STOPLIST = frozenset(
    {
        "net sales",
        "net income",
        "net earnings",
        "operating income",
        "operating profit",
        "operating profit margin",
        "segment profit",
        "gross profit",
        "net revenues",
        "cost of sales",
        "amortization",
        "depreciation and amortization",
        "income before income tax expense",
        "income tax",
        "income taxes",
        "income from operations",
        "operating expenses",
        "operating loss",  # gold-ambiguous pick
    }
)

# Segment measure groups: a group fires iff any term appears in the
# normalized table text; nmeas = number of firing groups.
SEGMENT_MEASURE_GROUPS = {
    "revenue": ("revenue", "sales"),
    "profit": (
        "operating income",
        "operating profit",
        "segment profit",
        "segment income",
        "ebitda",
    ),
    "pretax": ("income before income tax", "income before taxes"),
    "net_income": ("net income", "net earnings"),
    "assets": ("total assets", "segment assets"),
    "depr_capex": ("depreciation", "capital expenditures"),
}


@dataclass(frozen=True)
class CoreFormSpec:
    """Per-family parameters for the core-form evaluator."""

    family: str
    lexicon: tuple = ()
    col_stoplist: frozenset = frozenset()
    stub_stoplist: frozenset = frozenset()
    measure_groups: dict = field(default_factory=dict)


CORE_FORM_SPECS = {
    "intangibles": CoreFormSpec(family="intangibles", lexicon=INTANGIBLES_LEXICON),
    "fair_value": CoreFormSpec(family="fair_value"),
    "segment_reporting": CoreFormSpec(
        family="segment_reporting",
        col_stoplist=SEGMENT_COL_STOPLIST,
        stub_stoplist=SEGMENT_STUB_STOPLIST,
        measure_groups=SEGMENT_MEASURE_GROUPS,
    ),
}
