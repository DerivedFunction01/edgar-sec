"""Exhibit 98: Fairness Opinions (de-SPAC)."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex98",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="98",
    title="Fairness Opinions (de-SPAC)",
    tier="tier3",
    title_anchors=(
        "REPORT PURSUANT TO ITEM 1607",
        "FAIRNESS OPINION IN DE-SPAC TRANSACTION",
    ),
    primary_anchors=("FAIRNESS OPINION IN DE-SPAC TRANSACTION",),
    secondary_tokens=(
        "ITEM 1607(C) OF REGULATION S-K",
        "DE-SPAC TRANSACTION",
        "FAIRNESS FROM A FINANCIAL POINT OF VIEW",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
