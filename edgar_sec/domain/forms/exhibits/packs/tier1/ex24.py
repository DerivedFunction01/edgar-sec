"""Exhibit 24: Powers of Attorney."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex24",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="24",
    title="Powers of Attorney",
    tier="tier1",
    title_anchors=(
        "POWER OF ATTORNEY",
        "SPECIAL POWER OF ATTORNEY",
        "LIMITED POWER OF ATTORNEY",
    ),
    primary_anchors=("POWER OF ATTORNEY",),
    secondary_tokens=(
        "KNOW ALL BY THESE PRESENTS",
        "CONSTITUTES AND APPOINTS",
        "ATTORNEY-IN-FACT",
        "SECTION 16",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
