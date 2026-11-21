"""Exhibit 19: Insider Trading Policy."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex19",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="19",
    title="Insider Trading Policy",
    tier="tier2",
    title_anchors=(
        "INSIDER TRADING POLICY",
        "SECURITIES TRADING POLICY",
    ),
    primary_anchors=("INSIDER TRADING POLICY",),
    secondary_tokens=(
        "ITEM 408(B) OF REGULATION S-K",
        "MATERIAL NONPUBLIC INFORMATION",
        "RULE 10B5-1 TRADING PLANS",
        "BLACKOUT PERIODS",
    ),
    veto_signals=("CODE OF ETHICS",),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
