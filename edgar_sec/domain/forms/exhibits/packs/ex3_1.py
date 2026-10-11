"""Exhibit 3.1: Articles of Incorporation."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex3_1",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="3.1",
    title="Articles of Incorporation",
    parent_code="3",
    tier="tier1",
    title_anchors=(
        "ARTICLES OF INCORPORATION",
        "CERTIFICATE OF INCORPORATION",
        "CERTIFICATE OF FORMATION",
        "CHARTER",
        "RESTATED CERTIFICATE OF INCORPORATION",
    ),
    primary_anchors=(
        "ARTICLES OF INCORPORATION",
        "CERTIFICATE OF INCORPORATION",
    ),
    secondary_tokens=(
        "STATE OF INCORPORATION",
        "DOMESTIC CORPORATION",
        "AUTHORIZED SHARES",
        "CORPORATE GOVERNANCE",
    ),
    veto_signals=(
        "BYLAWS",
        "BY-LAWS",
        "AGREEMENT AND PLAN OF MERGER",
    ),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
