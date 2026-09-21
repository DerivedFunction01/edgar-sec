"""Declarative checkbox schemas and constraint definitions for SEC cover pages."""

from __future__ import annotations

from dataclasses import dataclass

from defs.sec_forms.vocabulary import (
    FILER_STATUS_GROUP,
    REPORT_PERIOD_GROUP,
    STAT_COMPLIANT_12_MONTHS,
    STAT_EGC_TRANSITION_OPTOUT,
    STAT_ERROR_CORRECTION,
    STAT_RECOVERY_ANALYSIS,
    STAT_SHELL,
    STAT_SOX_404B,
    STAT_VOLUNTARY,
    STAT_WKSI,
    STATUTORY_BINARY_GROUP,
)


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

__all__ = [
    "ANNUAL_CHECKBOX_SCHEMA",
    "QUARTERLY_CHECKBOX_SCHEMA",
    "STATUTORY_CHECKBOX_CONSTRAINTS",
    "CheckboxConstraint",
    "CoverCheckboxSchema",
]
