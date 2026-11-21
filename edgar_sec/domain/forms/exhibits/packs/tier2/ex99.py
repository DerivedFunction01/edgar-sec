"""Exhibit 99: Press Releases."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex99",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="99",
    title="Press Releases",
    tier="tier2",
    title_anchors=(
        "FOR IMMEDIATE RELEASE",
        "PRESS RELEASE",
        "ADDITIONAL EXHIBITS",
    ),
    primary_anchors=("FOR IMMEDIATE RELEASE",),
    secondary_tokens=(
        "DATELINE",
        "COMPANY TODAY ANNOUNCED",
        "CONFERENCE CALL DETAILS",
    ),
    veto_signals=("FORM 8-K",),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
