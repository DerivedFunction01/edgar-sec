"""Exhibit 9: Voting Trust Agreements."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex9",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="9",
    title="Voting Trust Agreements",
    tier="tier3",
    title_anchors=("VOTING TRUST AGREEMENT",),
    primary_anchors=("VOTING TRUST AGREEMENT",),
    secondary_tokens=(
        "VOTING TRUSTEE",
        "TRUST CERTIFICATES",
        "DEPOSIT OF SHARES",
    ),
    veto_signals=(),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
