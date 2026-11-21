"""Exhibit 106: Static Pool Information."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex106",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="106",
    title="Static Pool Information",
    tier="tier3",
    title_anchors=(
        "STATIC POOL INFORMATION",
        "STATIC POOL DISCLOSURE",
    ),
    primary_anchors=("STATIC POOL INFORMATION",),
    secondary_tokens=(
        "ITEM 1105 OF REGULATION AB",
        "CUMULATIVE NET LOSSES",
        "VINTAGE ORIGINATION YEAR",
        "POOL FACTOR",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
