"""Exhibit 18: Accounting Preferability Letters."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex18",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="18",
    title="Accounting Preferability Letters",
    tier="tier2",
    title_anchors=("LETTER RE PREFERABILITY OF ACCOUNTING PRINCIPLES",),
    primary_anchors=("LETTER RE PREFERABILITY OF ACCOUNTING PRINCIPLES",),
    secondary_tokens=(
        "PREFERABLE UNDER THE CIRCUMSTANCES",
        "CHANGE IN ACCOUNTING PRINCIPLE",
        "ACCOUNTING STANDARDS CODIFICATION",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
