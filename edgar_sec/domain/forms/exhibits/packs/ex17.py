"""Exhibit 17: Director Departure Correspondence."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex17",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="17",
    title="Director Departure Correspondence",
    tier="tier2",
    title_anchors=("CORRESPONDENCE ON DEPARTURE OF DIRECTOR",),
    primary_anchors=("CORRESPONDENCE ON DEPARTURE OF DIRECTOR",),
    secondary_tokens=(
        "ITEM 5.02 OF FORM 8-K",
        "DISAGREEMENT WITH THE REGISTRANT",
        "RESIGNATION LETTER",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
