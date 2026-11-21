"""Exhibit 21: Subsidiaries List."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex21",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="21",
    title="Subsidiaries",
    tier="tier1",
    title_anchors=(
        "SUBSIDIARIES OF",
        "SIGNIFICANT SUBSIDIARIES",
        "LIST OF SUBSIDIARIES",
    ),
    primary_anchors=(
        "SUBSIDIARIES OF",
        "SIGNIFICANT SUBSIDIARIES",
    ),
    secondary_tokens=(
        "JURISDICTION OF INCORPORATION",
        "PERCENTAGE OF OWNERSHIP",
        "STATE OR JURISDICTION",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
