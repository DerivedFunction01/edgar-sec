"""Exhibit 4: Indentures and Securities Descriptions."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex4",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="4",
    title="Industures and Securities Descriptions",
    tier="tier1",
    title_anchors=(
        "DESCRIPTION OF THE REGISTRANT'S SECURITIES",
        "INDENTURE",
        "SUPPLEMENTAL INDENTURE",
    ),
    primary_anchors=(
        "DESCRIPTION OF THE REGISTRANT'S SECURITIES",
        "INDENTURE",
    ),
    secondary_tokens=(
        "REGISTERED PURSUANT TO SECTION 12",
        "AS TRUSTEE",
        "SENIOR NOTES DUE",
        "TRUST INDENTURE ACT",
    ),
    veto_signals=(
        "CREDIT AGREEMENT",
        "BORROWER",
        "ADMINISTRATIVE AGENT",
    ),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
