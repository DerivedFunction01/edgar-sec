"""Exhibit 25: Form T-1."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex25",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="25",
    title="Form T-1",
    tier="tier2",
    title_anchors=(
        "FORM T-1",
        "STATEMENT OF ELIGIBILITY UNDER THE TRUST INDENTURE ACT",
    ),
    primary_anchors=("FORM T-1",),
    secondary_tokens=(
        "TRUST INDENTURE ACT OF 1939",
        "DESIGNATED TO ACT AS TRUSTEE",
        "COMPTROLLER OF THE CURRENCY",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
