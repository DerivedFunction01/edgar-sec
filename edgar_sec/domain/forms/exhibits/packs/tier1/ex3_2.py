"""Exhibit 3.2: Bylaws."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex3_2",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="3.2",
    title="Bylaws",
    parent_code="3",
    tier="tier1",
    title_anchors=(
        "BYLAWS",
        "BY-LAWS",
        "AMENDED AND RESTATED BYLAWS",
    ),
    primary_anchors=(
        "BYLAWS",
        "BY-LAWS",
    ),
    secondary_tokens=(
        "ARTICLE I",
        "OFFICES",
        "MEETINGS OF STOCKHOLDERS",
        "BOARD OF DIRECTORS",
    ),
    veto_signals=(
        "CERTIFICATE OF INCORPORATION",
        "ARTICLES OF INCORPORATION",
    ),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
