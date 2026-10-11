"""Exhibit 31.1: Corporate SOX 302 Certifications."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex31_i",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="31.1",
    title="Corporate SOX 302 Certifications",
    parent_code="31",
    tier="tier1",
    title_anchors=("CERTIFICATION OF CEO AND CFO PURSUANT TO SECTION 302",),
    primary_anchors=(
        "CERTIFY THAT",
        "I HAVE REVIEWED THIS",
        "RULES 13A-15(E) AND 15D-15(E)",
        "INTERNAL CONTROL OVER FINANCIAL REPORTING",
    ),
    secondary_tokens=(
        "RULE 13A-14(A)",
        "SECTION 302",
        "MATERIAL FACT",
        "FAIRLY PRESENT",
    ),
    veto_signals=(
        "ITEM 1123 OF REGULATION AB",
        "ITEM 1122 OF REGULATION AB",
    ),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
