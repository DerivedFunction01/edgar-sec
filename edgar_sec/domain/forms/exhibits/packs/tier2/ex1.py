"""Exhibit 1: Underwriting Agreements."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex1",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="1",
    title="Underwriting Agreements",
    tier="tier2",
    title_anchors=(
        "UNDERWRITING AGREEMENT",
        "PURCHASE AGREEMENT",
    ),
    primary_anchors=(
        "UNDERWRITING AGREEMENT",
        "PURCHASE AGREEMENT",
    ),
    secondary_tokens=(
        "UNDERWRITERS",
        "REPRESENTATIVES OF THE SEVERAL UNDERWRITERS",
        "UNDERWRITING COMMISSION",
    ),
    veto_signals=("LOAN AND MERGER AGREEMENT",),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
