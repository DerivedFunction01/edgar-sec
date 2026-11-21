"""Exhibit 97: Clawback Policy."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex97",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="97",
    title="Clawback Policy",
    tier="tier2",
    title_anchors=(
        "POLICY FOR RECOVERY OF ERRONEOUSLY AWARDED COMPENSATION",
        "CLAWBACK POLICY",
    ),
    primary_anchors=("CLAWBACK POLICY",),
    secondary_tokens=(
        "RULE 10D-1 OF THE EXCHANGE ACT",
        "ACCOUNTING RESTATEMENT",
        "INCENTIVE-BASED COMPENSATION",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
