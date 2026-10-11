"""Exhibit 2: M&A Agreements."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex2",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="2",
    title="Merger and Acquisition Agreements",
    tier="tier2",
    title_anchors=(
        "AGREEMENT AND PLAN OF MERGER",
        "AGREEMENT AND PLAN OF REORGANIZATION",
        "ASSET PURCHASE AGREEMENT",
        "STOCK PURCHASE AGREEMENT",
    ),
    primary_anchors=(
        "AGREEMENT AND PLAN OF MERGER",
        "ASSET PURCHASE AGREEMENT",
    ),
    secondary_tokens=(
        "MERGER SUB",
        "SURVIVING CORPORATION",
        "PURCHASED ASSETS",
        "EXCLUDED LIABILITIES",
    ),
    veto_signals=("LOAN AND MERGER AGREEMENT",),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
