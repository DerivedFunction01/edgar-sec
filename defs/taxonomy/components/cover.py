"""Canonical cover page, entity coordinate, and regulatory checkbox concepts."""

from __future__ import annotations

from dataclasses import dataclass

from defs.sec_forms.vocabulary import (
    ACCELERATED_FILER,
    COVER_LABELS,
    EMERGING_GROWTH_COMPANY,
    LARGE_ACCELERATED_FILER,
    NON_ACCELERATED_FILER,
    SECURITIES_12B_ANCHOR_TERMS,
    SECURITIES_12B_SUPPORT_TERMS,
    SHELL_COMPANY,
    SMALLER_REPORTING_COMPANY,
    VOLUNTARY_FILER,
    WELL_KNOWN_SEASONED_ISSUER,
)
from defs.taxonomy.tables.shapes import ShapeConstraint
from defs.taxonomy.tables.specs import (
    RepairPolicy,
    TableFamilySpec,
    TableScope,
    build_ngram_tier,
)
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack

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

SECURITIES_12B_ANCHORS = SECURITIES_12B_ANCHOR_TERMS
SECURITIES_12B_SUPPORT = SECURITIES_12B_SUPPORT_TERMS

# --- Filer Status Category & Regulatory Checkbox Concepts ---------------------

FILER_STATUS_TERMS: tuple[str, ...] = (
    LARGE_ACCELERATED_FILER,
    ACCELERATED_FILER,
    NON_ACCELERATED_FILER,
    SMALLER_REPORTING_COMPANY,
    EMERGING_GROWTH_COMPANY,
    SHELL_COMPANY,
    WELL_KNOWN_SEASONED_ISSUER,
    VOLUNTARY_FILER,
    "indicate by check mark",
    "auditor attestation",
)

# --- Checkbox constraint vocabulary --------------------------------------------

REPORT_PERIOD_GROUP = "report_period"
FILER_STATUS_GROUP = "filer_status"
STATUTORY_BINARY_GROUP = "statutory_binary"

REPORT_ANNUAL = "annual"
REPORT_QUARTERLY = "quarterly"
REPORT_TRANSITION = "transition"

FILER_LARGE_ACCELERATED = "large_accelerated_filer"
FILER_ACCELERATED = "accelerated_filer"
FILER_NON_ACCELERATED = "non_accelerated_filer"
FILER_SMALLER_REPORTING = "smaller_reporting_company"
FILER_EMERGING_GROWTH = "emerging_growth_company"

STAT_WKSI = "well_known_seasoned_issuer"
STAT_SHELL = "shell_company"
STAT_VOLUNTARY = "voluntary_filer"
STAT_COMPLIANT_12_MONTHS = "compliant_12_months"
STAT_SOX_404B = "sox_404b"
STAT_EGC_TRANSITION_OPTOUT = "egc_transition_optout"
STAT_ERROR_CORRECTION = "error_correction"
STAT_RECOVERY_ANALYSIS = "recovery_analysis"


@dataclass(frozen=True, slots=True)
class CheckboxConstraint:
    """One named Boolean relationship in a form checkbox schema."""

    name: str
    relation: str
    left: str
    right: str
    left_state: str = "checked"
    right_state: str = "checked"
    penalty: int = 300
    description: str = ""


@dataclass(frozen=True, slots=True)
class CoverCheckboxSchema:
    """Form-scoped checkbox groups and constraints."""

    family: str
    groups: tuple[str, ...]
    constraints: tuple[CheckboxConstraint, ...] = ()


STATUTORY_CHECKBOX_CONSTRAINTS: tuple[CheckboxConstraint, ...] = (
    CheckboxConstraint(
        name="wksi_shell_exclusion",
        relation="not_both",
        left=STAT_WKSI,
        right=STAT_SHELL,
        description="WKSI and shell company cannot both be yes.",
    ),
    CheckboxConstraint(
        name="wksi_voluntary_filer_exclusion",
        relation="not_both",
        left=STAT_WKSI,
        right=STAT_VOLUNTARY,
        description="WKSI and voluntary filer cannot both be yes.",
    ),
    CheckboxConstraint(
        name="wksi_12_month_compliance",
        relation="implies",
        left=STAT_WKSI,
        right=STAT_COMPLIANT_12_MONTHS,
        description="WKSI requires timely filing compliance for twelve months.",
    ),
    CheckboxConstraint(
        name="wksi_404b_required",
        relation="implies",
        left=STAT_WKSI,
        right=STAT_SOX_404B,
        description="WKSI requires the applicable 404(b) attestation state.",
    ),
    CheckboxConstraint(
        name="shell_404b_exemption",
        relation="implies",
        left=STAT_SHELL,
        right=STAT_SOX_404B,
        right_state="unchecked",
        description="Shell company status excludes a 404(b) yes state.",
    ),
    CheckboxConstraint(
        name="egc_wksi_exclusion",
        relation="not_both",
        left=STAT_EGC_TRANSITION_OPTOUT,
        right=STAT_WKSI,
        description="EGC transition opt-out and WKSI cannot both be yes.",
    ),
    CheckboxConstraint(
        name="recovery_requires_error_correction",
        relation="implies",
        left=STAT_RECOVERY_ANALYSIS,
        right=STAT_ERROR_CORRECTION,
        description="Recovery analysis requires an error correction.",
    ),
)

ANNUAL_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="annual",
    groups=(REPORT_PERIOD_GROUP, FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
)
QUARTERLY_CHECKBOX_SCHEMA = CoverCheckboxSchema(
    family="quarterly",
    groups=(REPORT_PERIOD_GROUP, FILER_STATUS_GROUP, STATUTORY_BINARY_GROUP),
    constraints=STATUTORY_CHECKBOX_CONSTRAINTS,
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
