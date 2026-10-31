"""Exhibit 32.1: SOX 906 Certifications (Section 1350)."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex32",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="32.1",
    title="SOX 906 Certifications",
    parent_code="32",
    tier="tier1",
    title_anchors=("CERTIFICATION OF CEO AND CFO PURSUANT TO SECTION 906",),
    primary_anchors=(
        "18 U.S.C. SECTION 1350",
        "SECTION 906",
        "FULLY COMPLIES WITH THE REQUIREMENTS OF SECTION 13(A)",
        "FAIRLY PRESENTS, IN ALL MATERIAL RESPECTS",
    ),
    secondary_tokens=(
        "SARBANES-OXLEY ACT OF 2002",
        "ACCOMPANIES THE REPORT",
        "IS BEING FURNISHED SOLELY PURSUANT TO",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
