"""SEC Regulation S-K Item 703 (Issuer Purchases of Equity Securities) concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

SHARES_PURCHASED_STATUTORY_PHRASES: dict[str, tuple[str, ...]] = {
    "P1_total_shares": (
        "total number of shares purchased",
        "total number of shares repurchased",
        "total number of shares (or units) purchased",
        "total shares purchased",
    ),
    "P2_avg_price": (
        "average price paid per share",
        "average price paid per common share",
        "average price paid per share (or unit)",
    ),
    "P3_announced": (
        "total number of shares purchased as part of publicly announced plans or programs",
        "purchased as part of publicly announced plans or programs",
        "part of publicly announced plans or programs",
        "publicly announced plans or programs",
    ),
    "P4_yet_purchasable": (
        "approximate dollar value of shares that may yet be purchased under the plans or programs",
        "approximate dollar value of shares that may yet be purchased",
        "dollar value of shares that may yet be purchased",
        "maximum number of shares that may yet be purchased",
        "shares that may yet be purchased under the plans or programs",
        "shares that may yet be purchased",
    ),
}

CANONICAL_REPURCHASE_HEADERS: tuple[str, ...] = (
    "Period",
    "Total Number of Shares Purchased",
    "Average Price Paid Per Share",
    "Total Number of Shares Purchased as Part of Publicly Announced Plans or Programs",
    "Approximate Dollar Value of Shares That May Yet Be Purchased Under the Plans or Programs",
)

_shares_phrases: tuple[str, ...] = tuple(
    phrase
    for phrases in SHARES_PURCHASED_STATUTORY_PHRASES.values()
    for phrase in phrases
)

_SHARES_PURCHASED_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="shares_purchased",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "statutory_phrases",
                    _shares_phrases,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
            )
            if t is not None
        ),
    )
)

SHARES_PURCHASED_SPEC = TableFamilySpec(
    name="shares_purchased",
    shape=ShapeConstraint(min_rows=3, max_rows=25, min_cols=4),
    evidence_pack=_SHARES_PURCHASED_PACK,
    repair_policy=RepairPolicy.FAMILY_TEMPLATE,
    candidate_default_scope=TableScope.BODY,
)
