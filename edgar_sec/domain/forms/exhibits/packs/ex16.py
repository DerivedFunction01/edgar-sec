"""Exhibit 16: Change in Certifying Accountant."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex16",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="16",
    title="Change in Certifying Accountant",
    tier="tier2",
    title_anchors=("LETTER RE CHANGE IN CERTIFYING ACCOUNTANT",),
    primary_anchors=("LETTER RE CHANGE IN CERTIFYING ACCOUNTANT",),
    secondary_tokens=(
        "ITEM 4.01 OF FORM 8-K",
        "ITEM 304 OF REGULATION S-K",
        "WE HAVE READ THE STATEMENTS MADE BY",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
