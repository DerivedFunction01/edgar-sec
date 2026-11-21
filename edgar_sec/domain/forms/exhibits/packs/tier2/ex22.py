"""Exhibit 22: Subsidiary Guarantors."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex22",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="22",
    title="Subsidiary Guarantors",
    tier="tier2",
    title_anchors=(
        "SUBSIDIARY GUARANTORS",
        "LIST OF GUARANTORS",
    ),
    primary_anchors=("SUBSIDIARY GUARANTORS",),
    secondary_tokens=(
        "RULE 13-01 OF REGULATION S-X",
        "GUARANTOR OF REGISTERED DEBT SECURITIES",
        "PLEDGED AFFILIATES",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
