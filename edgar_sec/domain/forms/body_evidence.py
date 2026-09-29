"""Body-prose evidence vocabulary for cover/body boundary detection.

The cover boundary ends where substantive body prose begins, which is a lexical
decision: a cover is dense with identity labels and short field values, while
body prose is narrative. These tiers are the vocabulary that separates them.

Ported from v1's per-form evidence packs, which carried one pack per form
(annual / quarterly / current report) differing only in vocabulary breadth.
v2 uses a single generic pack: the annual pack was a superset of the other two
for every tier the boundary actually consults, so splitting it per form
reproduced data without reproducing a distinction.
"""

from __future__ import annotations

# Decisive body phrases: one distinct phrase hit confirms body prose.
BODY_STRONG_PHRASES: tuple[str, ...] = (
    "collective bargaining",
    "labor union",
    "market segments",
    "management believes",
    "future cash flows",
    "assumptions and estimates",
)

# Corroborating body phrases with observed cover-prefix collision (a cover may
# quote forward-looking boilerplate, or TOC/notice text repeats it). One hit is
# support evidence only; a soft phrase alone never clears the decision gate.
BODY_SOFT_PHRASES: tuple[str, ...] = (
    "safe harbor",
    "cautionary statements",
    "undue reliance",
    "statements include",
    "future performance",
    "unless the context",
)

# Curated high-confidence early-body unigrams. Two distinct terms clear the
# strong tier; the two-term minimum reflects a sampled, not exhaustive, probe.
BODY_STRONG_TERMS: tuple[str, ...] = (
    "founded",
    "organized",
    "leading",
    "provider",
    "primarily",
    "overview",
    "engaged",
    "operated",
    "located",
    "manufacturing",
    "worldwide",
    "segments",
    "commenced",
    "began",
    "manufacturer",
    "range",
    "focus",
    "focused",
    "specialty",
    "headquartered",
    "subsidiaries",
    "acquired",
    "employees",
    "customers",
    "suppliers",
    "facilities",
    "competition",
)

BODY_VERBS: tuple[str, ...] = (
    "provides",
    "operates",
    "manufactures",
    "sells",
    "develops",
    "distributes",
    "manages",
    "expects",
    "believes",
    "anticipates",
)

# Weaker body-leaning vocabulary: two distinct terms are required to count.
BODY_WEAK_TERMS: tuple[str, ...] = (
    *BODY_VERBS,
    "products",
    "services",
    "operations",
    "sales",
    "revenue",
    "fiscal",
    "approximately",
    "markets",
    "industry",
    "network",
)

# Forward-looking vocabulary. "may" is deliberately absent: fold-mode matching
# would also match the month name "May".
BODY_FORWARD_TERMS: tuple[str, ...] = (
    "forward",
    "looking",
    "actual",
    "results",
    "materially",
    "risks",
    "differ",
    "uncertainties",
    "believe",
    "expect",
    "anticipate",
    "estimate",
    "intend",
    "following",
)

# Terms that mark cover-only context. A paragraph carrying one of these is not
# body prose no matter how much narrative vocabulary it also contains.
COVER_EXCLUSION_TERMS: tuple[str, ...] = (
    "commission file number",
    "exact name of registrant",
    "state or other jurisdiction",
    "principal executive offices",
    "securities registered pursuant",
    "name of each exchange",
    "trading symbol",
    "aggregate market value",
    "shares of common stock outstanding",
    "check the appropriate box",
    "emerging growth company",
    "smaller reporting company",
)

# Semantic section headings whose presence marks the start of substantive
# discussion, independent of PART/ITEM structure.
BODY_SEMANTIC_HEADINGS: tuple[str, ...] = (
    "management's discussion and analysis",
    "risk factors",
    "forward-looking statements",
    "forward looking statements",
    "quantitative and qualitative disclosures",
    "business",
    "properties",
    "legal proceedings",
    "market for registrant's",
    "management's report on",
    "controls and procedures",
    "exhibits and financial statement schedules",
    "financial statements and supplementary data",
)

__all__ = [
    "BODY_FORWARD_TERMS",
    "BODY_SEMANTIC_HEADINGS",
    "BODY_SOFT_PHRASES",
    "BODY_STRONG_PHRASES",
    "BODY_STRONG_TERMS",
    "BODY_VERBS",
    "BODY_WEAK_TERMS",
    "COVER_EXCLUSION_TERMS",
]
