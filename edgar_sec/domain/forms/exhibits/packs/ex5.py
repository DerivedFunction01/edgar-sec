"""Exhibit 5: Legal Opinions."""

from edgar_sec.domain.forms.common.exhibits import ExhibitPack

PACK = ExhibitPack(
    pack_id="ex5",
    version="v1",
    authority_id="reg_s_k_item_601",
    target_code="5",
    title="Legal Opinions",
    tier="tier2",
    title_anchors=(
        "OPINION OF COUNSEL",
        "VALIDITY OF THE SECURITIES",
        "LEGALITY OPINION",
    ),
    primary_anchors=("OPINION OF COUNSEL",),
    secondary_tokens=(
        "VALIDLY ISSUED, FULLY PAID AND NON-ASSESSABLE",
        "LEGALLY VALID AND BINDING OBLIGATIONS",
    ),
    veto_signals=("INTERNAL REVENUE CODE",),
    min_confidence_band="high",
    evaluator_quality="source_supported",
)

__all__ = ["PACK"]
