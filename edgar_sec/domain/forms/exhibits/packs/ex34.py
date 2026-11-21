"""Exhibit 34: Independent Accountant Attestation."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex34",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="34",
    title="Independent Accountant Attestation",
    tier="tier3",
    title_anchors=(
        "ATTESTATION REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM",
    ),
    primary_anchors=(
        "ATTESTATION REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM",
    ),
    secondary_tokens=(
        "EXAMINATION OF MANAGEMENT'S ASSERTION",
        "ITEM 1122(B) OF REGULATION AB",
        "AT-C SECTION 315",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
