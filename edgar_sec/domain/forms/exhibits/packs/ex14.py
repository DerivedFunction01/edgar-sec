"""Exhibit 14: Code of Ethics."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex14",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="14",
    title="Code of Ethics",
    tier="tier2",
    title_anchors=(
        "CODE OF ETHICS",
        "CODE OF BUSINESS CONDUCT AND ETHICS",
    ),
    primary_anchors=("CODE OF ETHICS",),
    secondary_tokens=(
        "ITEM 406 OF REGULATION S-K",
        "PRINCIPAL EXECUTIVE OFFICER",
        "PRINCIPAL FINANCIAL OFFICER",
    ),
    veto_signals=("EMPLOYEE HANDBOOK",),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
