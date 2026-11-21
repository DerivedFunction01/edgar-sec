"""Exhibit 10: Material Contracts."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex10",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="10",
    title="Material Contracts",
    tier="tier1",
    title_anchors=(
        "CREDIT AGREEMENT",
        "EMPLOYMENT AGREEMENT",
        "SEVERANCE AGREEMENT",
        "SERVICES AGREEMENT",
        "LEASE AGREEMENT",
    ),
    primary_anchors=(
        "CREDIT AGREEMENT",
        "EMPLOYMENT AGREEMENT",
        "SEVERANCE AGREEMENT",
    ),
    secondary_tokens=(
        "ADMINISTRATIVE AGENT",
        "LENDERS",
        "BORROWER",
        "EXECUTIVE",
        "BASE SALARY",
    ),
    veto_signals=(
        "INDENTURE",
        "AS TRUSTEE",
        "FORM OF PROXY",
    ),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
