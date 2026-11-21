"""Exhibit 31.2: ABS Servicing Certifications."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex31_ii",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="31.2",
    title="ABS Servicing Certifications",
    parent_code="31",
    tier="tier3",
    title_anchors=("CERTIFICATION OF CEO AND CFO PURSUANT TO SECTION 302",),
    primary_anchors=(
        "CERTIFY THAT",
        "I HAVE REVIEWED THIS REPORT",
        "SERVICING CRITERIA",
    ),
    secondary_tokens=("SERVICING CRITERIA",),
    veto_signals=(
        "ITEM 1123 OF REGULATION AB",
        "ITEM 1122 OF REGULATION AB",
    ),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
