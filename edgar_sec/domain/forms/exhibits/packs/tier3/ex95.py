"""Exhibit 95: Mine Safety Disclosures."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex95",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="95",
    title="Mine Safety Disclosures",
    tier="tier3",
    title_anchors=(
        "MINE SAFETY DISCLOSURE",
        "MINE SAFETY",
    ),
    primary_anchors=("MINE SAFETY DISCLOSURE",),
    secondary_tokens=(
        "SECTION 1503(A) OF THE DODD-FRANK ACT",
        "FEDERAL MINE SAFETY AND HEALTH ACT OF 1977",
        "MSHA",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
