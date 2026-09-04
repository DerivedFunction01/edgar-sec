"""Canonical cover page, entity coordinate, and regulatory checkbox concepts."""

from __future__ import annotations

from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

# --- Entity Coordinate Terms (Anchors vs. Qualifiers) --------------------------

STATE_OF_INCORPORATION_TERMS: tuple[str, ...] = (
    "state or other jurisdiction of incorporation or organization",
    "state or other jurisdiction of incorporation",
    "jurisdiction of incorporation",
    "state of incorporation",
    "state of organization",
)

IRS_EIN_TERMS: tuple[str, ...] = (
    "i.r.s. employer identification no.",
    "irs employer identification no.",
    "employer identification number",
    "employer identification no.",
    "taxpayer identification number",
    "i.r.s. no.",
    "irs no.",
)

COMMISSION_FILE_TERMS: tuple[str, ...] = (
    "commission file number",
    "sec file number",
    "file number",
)

REGISTRANT_NAME_TERMS: tuple[str, ...] = (
    "exact name of registrant as specified in its charter",
    "name of registrant as specified in its charter",
    "exact name of registrant",
    "name of registrant",
    "name of small business issuer as specified in its charter",
    "name of small business issuer",
)

PRINCIPAL_ADDRESS_TERMS: tuple[str, ...] = (
    "address of principal executive offices",
    "principal executive offices",
)

ZIP_CODE_TERMS: tuple[str, ...] = (
    "zip code",
    "postal code",
    "zip",
    "postal",
)

TELEPHONE_TERMS: tuple[str, ...] = (
    "registrant's telephone number, including area code",
    "registrant telephone number, including area code",
    "issuer's telephone number, including area code",
    "issuer's telephone number",
    "telephone number, including area code",
    "telephone number",
)

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

# --- Filer Status Category & Regulatory Checkbox Concepts ---------------------

FILER_STATUS_TERMS: tuple[str, ...] = (
    "large accelerated filer",
    "accelerated filer",
    "non-accelerated filer",
    "smaller reporting company",
    "emerging growth company",
    "shell company",
    "well-known seasoned issuer",
    "voluntary filer",
    "indicate by check mark",
    "auditor attestation",
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
