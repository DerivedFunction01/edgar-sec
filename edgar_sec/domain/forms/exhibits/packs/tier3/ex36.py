"""Exhibit 36: Shelf Offerings Certification."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex36",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="36",
    title="Shelf Offerings Certification",
    tier="tier3",
    title_anchors=("CERTIFICATION FOR SHELF OFFERINGS OF ASSET-BACKED SECURITIES",),
    primary_anchors=("CERTIFICATION FOR SHELF OFFERINGS OF ASSET-BACKED SECURITIES",),
    secondary_tokens=(
        "GENERAL INSTRUCTION I.B.1.(A) OF FORM SF-3",
        "CHARACTERISTICS OF THE SECURITIZED ASSETS",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
