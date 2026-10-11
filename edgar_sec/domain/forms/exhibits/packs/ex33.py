"""Exhibit 33: Compliance Assessment Reports."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex33",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="33",
    title="ABS Compliance Assessment Reports",
    tier="tier3",
    title_anchors=(
        "REPORT ON ASSESSMENT OF COMPLIANCE WITH APPLICABLE SERVICING CRITERIA",
    ),
    primary_anchors=(
        "REPORT ON ASSESSMENT OF COMPLIANCE WITH APPLICABLE SERVICING CRITERIA",
    ),
    secondary_tokens=(
        "ITEM 1122(D) OF REGULATION AB",
        "PLATFORM",
        "MATERIAL INSTANCES OF NONCOMPLIANCE",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
