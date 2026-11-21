"""Exhibit 20: Section 15(D) Statements."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex20",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="20",
    title="Section 15(D) Statements",
    tier="tier3",
    title_anchors=(
        "STATEMENT PURSUANT TO SECTION 15(D)",
        "STATEMENT TO SECURITY HOLDERS",
    ),
    primary_anchors=("STATEMENT PURSUANT TO SECTION 15(D)",),
    secondary_tokens=(
        "PERIODIC DISTRIBUTION TO CERTIFICATE HOLDERS",
        "SERVICING REMITTANCE",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
