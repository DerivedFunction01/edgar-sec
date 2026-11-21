"""Exhibit 8: Tax Opinions."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex8",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="8",
    title="Tax Opinions",
    tier="tier2",
    title_anchors=(
        "TAX OPINION",
        "FEDERAL INCOME TAX MATTERS",
    ),
    primary_anchors=("TAX OPINION",),
    secondary_tokens=(
        "INTERNAL REVENUE CODE OF 1986",
        "SECTION 368",
        "QUALIFIES AS A REAL ESTATE INVESTMENT TRUST UNDER SECTION 856",
    ),
    veto_signals=("CORPORATE VALIDITY",),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
