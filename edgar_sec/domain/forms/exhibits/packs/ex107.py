"""Exhibit 107: Filing Fee Tables."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex107",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="107",
    title="Filing Fee Tables",
    tier="tier2",
    title_anchors=(
        "FILING FEE TABLE",
        "CALCULATION OF FILING FEE TABLES",
    ),
    primary_anchors=("FILING FEE TABLE",),
    secondary_tokens=(
        "TABLE 1: NEWLY REGISTERED AND CARRY FORWARD SECURITIES",
        "RULE 457",
        "FEE CALCULATION",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
