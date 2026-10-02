"""Canonical cover page, entity coordinate, and regulatory checkbox concepts."""

from __future__ import annotations

from edgar_sec.domain.forms.common.vocabulary import (
    COVER_LABELS,
    FILER_STATUS_TERMS,
)
from edgar_sec.domain.taxonomy.tables.shapes import ShapeConstraint
from edgar_sec.domain.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from edgar_sec.foundation.text.evidence import (
    LexicalEvidencePack,
    compile_evidence_pack,
)

# --- Entity Coordinate Terms (Anchors vs. Qualifiers) --------------------------

STATE_OF_INCORPORATION_TERMS = COVER_LABELS["state_of_incorporation"]
IRS_EIN_TERMS = COVER_LABELS["irs_ein"]
COMMISSION_FILE_TERMS = COVER_LABELS["commission_file_number"]
REGISTRANT_NAME_TERMS = COVER_LABELS["registrant_name"]
PRINCIPAL_ADDRESS_TERMS = COVER_LABELS["principal_address"]
ZIP_CODE_TERMS = COVER_LABELS["zip_code"]
TELEPHONE_TERMS = COVER_LABELS["telephone"]

COVER_ENTITY_ANCHORS: dict[str, tuple[str, ...]] = {
    "state_of_incorporation": STATE_OF_INCORPORATION_TERMS,
    "irs_ein": IRS_EIN_TERMS,
    "commission_file_number": COMMISSION_FILE_TERMS,
    "registrant_name": REGISTRANT_NAME_TERMS,
}

COVER_ENTITY_QUALIFIERS: dict[str, tuple[str, ...]] = {
    "principal_address": PRINCIPAL_ADDRESS_TERMS,
    "zip_code": ZIP_CODE_TERMS,
    "telephone": TELEPHONE_TERMS,
}

ALL_ENTITY_COORDINATE_FIELDS: dict[str, tuple[str, ...]] = {
    **COVER_ENTITY_ANCHORS,
    **COVER_ENTITY_QUALIFIERS,
}

# --- Securities Registered Pursuant to Section 12(b) / 12(g) ------------------

SECURITIES_12B_ANCHORS: tuple[str, ...] = (
    "securities registered pursuant to section 12(b) of the act",
    "securities registered pursuant to section 12(b)",
    "securities registered pursuant to section 12(g)",
    "securities registered under section 12",
    "trading symbol(s)",
    "trading symbol",
    "title of each class",
    "name of each exchange on which registered",
)

SECURITIES_12B_SUPPORT: tuple[str, ...] = (
    "title of class",
    "trading symbols",
    "par value",
)

# --- Universal Cover Disqualifiers (Vetoes) -----------------------------------

COVER_VETO_TERMS: tuple[str, ...] = (
    "amortization",
    "depreciation",
    "reconciliation",
    "liabilities",
    "stockholders",
    "shareholders",
)

# --- Compiled Family Specs ----------------------------------------------------

_cover_anchors: tuple[str, ...] = tuple(
    phrase for phrases in COVER_ENTITY_ANCHORS.values() for phrase in phrases
)
_cover_qualifiers: tuple[str, ...] = tuple(
    phrase for phrases in COVER_ENTITY_QUALIFIERS.values() for phrase in phrases
)

_COVER_LAYOUT_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="cover_layout",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier("anchors", _cover_anchors, priority=10, value=2),
                build_ngram_tier(
                    "qualifiers", _cover_qualifiers, priority=5, value=1, support=True
                ),
            )
            if t is not None
        ),
        exclusion_terms=COVER_VETO_TERMS,
    )
)

COVER_LAYOUT_SPEC = TableFamilySpec(
    name="cover_layout",
    shape=ShapeConstraint(min_rows=2, max_rows=6, max_rows_scoped=35, max_cols=6),
    evidence_pack=_COVER_LAYOUT_PACK,
    repair_policy=RepairPolicy.PRESENTATION_ONLY,
    candidate_default_scope=TableScope.COVER,
)

_CHECKBOX_GRID_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="checkbox_grid",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "status_terms", FILER_STATUS_TERMS, priority=10, value=2
                ),
            )
            if t is not None
        ),
    )
)

CHECKBOX_GRID_SPEC = TableFamilySpec(
    name="checkbox_grid",
    shape=ShapeConstraint(
        min_rows=1, max_rows=10, max_cols=8, max_numeric_density=0.10
    ),
    evidence_pack=_CHECKBOX_GRID_PACK,
    repair_policy=RepairPolicy.PRESENTATION_ONLY,
    candidate_default_scope=TableScope.COVER,
)

_REGISTRATION_TABLE_PACK = compile_evidence_pack(
    LexicalEvidencePack(
        name="registration_table",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "anchors", SECURITIES_12B_ANCHORS, priority=10, value=2
                ),
                build_ngram_tier(
                    "support", SECURITIES_12B_SUPPORT, priority=5, value=1, support=True
                ),
            )
            if t is not None
        ),
    )
)

REGISTRATION_TABLE_SPEC = TableFamilySpec(
    name="registration_table",
    shape=ShapeConstraint(min_rows=2, max_rows=12, max_cols=6),
    evidence_pack=_REGISTRATION_TABLE_PACK,
    repair_policy=RepairPolicy.PRESENTATION_ONLY,
    candidate_default_scope=TableScope.COVER,
)

__all__ = [
    "ALL_ENTITY_COORDINATE_FIELDS",
    "CHECKBOX_GRID_SPEC",
    "COMMISSION_FILE_TERMS",
    "COVER_ENTITY_ANCHORS",
    "COVER_ENTITY_QUALIFIERS",
    "COVER_LAYOUT_SPEC",
    "COVER_VETO_TERMS",
    "IRS_EIN_TERMS",
    "PRINCIPAL_ADDRESS_TERMS",
    "REGISTRANT_NAME_TERMS",
    "REGISTRATION_TABLE_SPEC",
    "SECURITIES_12B_ANCHORS",
    "SECURITIES_12B_SUPPORT",
    "STATE_OF_INCORPORATION_TERMS",
    "TELEPHONE_TERMS",
    "ZIP_CODE_TERMS",
]
