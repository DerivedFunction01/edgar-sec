"""Exhibit 23: Consents."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex23",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="23",
    title="Consents",
    tier="tier1",
    title_anchors=(
        "CONSENT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM",
        "CONSENT OF INDEPENDENT AUDITORS",
        "CONSENT OF COUNSEL",
    ),
    primary_anchors=(
        "CONSENT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM",
        "CONSENT OF INDEPENDENT AUDITORS",
    ),
    secondary_tokens=(
        "WE CONSENT TO THE INCORPORATION BY REFERENCE",
        "REPORT OF INDEPENDENT",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
