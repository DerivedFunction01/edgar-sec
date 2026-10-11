"""Exhibit 96: Technical Report Summaries."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex96",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="96",
    title="Technical Report Summaries",
    tier="tier3",
    title_anchors=(
        "TECHNICAL REPORT SUMMARY",
        "S-K 1300 TECHNICAL REPORT SUMMARY",
    ),
    primary_anchors=("TECHNICAL REPORT SUMMARY",),
    secondary_tokens=(
        "SUBPART 1300 OF REGULATION S-K",
        "QUALIFIED PERSON",
        "MINERAL RESOURCES AND MINERAL RESERVES",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
