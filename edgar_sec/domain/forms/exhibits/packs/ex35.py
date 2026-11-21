"""Exhibit 35: Servicer Compliance Statements."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex35",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="35",
    title="Servicer Compliance Statements",
    tier="tier3",
    title_anchors=("SERVICER COMPLIANCE STATEMENT",),
    primary_anchors=("SERVICER COMPLIANCE STATEMENT",),
    secondary_tokens=(
        "ITEM 1123 OF REGULATION AB",
        "OFFICER'S CERTIFICATE",
        "FULFILLED ALL OF ITS OBLIGATIONS",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
