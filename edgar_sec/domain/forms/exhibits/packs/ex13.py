"""Exhibit 13: Annual Reports to Security Holders."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex13",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="13",
    title="Annual Reports to Security Holders",
    tier="tier3",
    title_anchors=(
        "ANNUAL REPORT TO SECURITY HOLDERS",
        "LETTER TO SHAREHOLDERS",
    ),
    primary_anchors=("ANNUAL REPORT TO SECURITY HOLDERS",),
    secondary_tokens=(
        "TO OUR SHAREHOLDERS",
        "FINANCIAL HIGHLIGHTS",
        "FELLOW STOCKHOLDERS",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
