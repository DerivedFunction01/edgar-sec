"""Exhibit 15: Auditor Comfort Letters."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex15",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="15",
    title="Auditor Comfort Letters",
    tier="tier2",
    title_anchors=("LETTER RE UNAUDITED INTERIM FINANCIAL INFORMATION",),
    primary_anchors=("LETTER RE UNAUDITED INTERIM FINANCIAL INFORMATION",),
    secondary_tokens=(
        "RULE 436(C) OF THE SECURITIES ACT",
        "INTERIM FINANCIAL INFORMATION",
        "ACKNOWLEDGEMENT OF AWARENESS",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
