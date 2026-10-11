"""Declarative checkbox schemas and constraint definitions for SEC cover pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from edgar_sec.domain.forms.common.vocabulary import (
    AUDITOR_ATTESTATION_TERM,
    ERROR_CORRECTION_TERM,
    FILER_STATUS_GROUP,
    FILER_TYPE_LABELS,
    NOT_REQUIRED_TO_FILE_TERM,
    PRECEDING_12_MONTHS_TERM,
    RECOVERY_ANALYSIS_TERM,
    REPORT_PERIOD_GROUP,
    REQUIRED_REPORTS_TERM,
    SHELL_COMPANY,
    STAT_COMPLIANT_12_MONTHS,
    STAT_EGC_TRANSITION_OPTOUT,
    STAT_ERROR_CORRECTION,
    STAT_RECOVERY_ANALYSIS,
    STAT_SHELL,
    STAT_SOX_404B,
    STAT_VOLUNTARY,
    STAT_WKSI,
    STATUTORY_BINARY_GROUP,
    VOLUNTARY_FILER,
    WELL_KNOWN_SEASONED_ISSUER,
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
class CheckboxLabelSpec:
    key: str
    phrases: tuple[str, ...]
    group: str
    period_role: Literal["companion", "transition"] | None = None


@dataclass(frozen=True, slots=True)
class CoverCheckboxSchema:
    """Form-scoped checkbox groups and constraints."""

    family: str
    groups: tuple[str, ...]
    constraints: tuple[CheckboxConstraint, ...] = ()
    labels: tuple[CheckboxLabelSpec, ...] = ()

    @property
    def report_period_companion(self) -> str | None:
        return self._period_key("companion")

    @property
    def report_period_transition(self) -> str | None:
        return self._period_key("transition")

    def _period_key(self, role: Literal["companion", "transition"]) -> str | None:
        return next(
            (label.key for label in self.labels if label.period_role == role),
            None,
        )


COMMON_CHECKBOX_LABELS: tuple[CheckboxLabelSpec, ...] = (
    *(
        CheckboxLabelSpec(key, phrases, FILER_STATUS_GROUP)
        for key, phrases in FILER_TYPE_LABELS.items()
    ),
    CheckboxLabelSpec(
        STAT_WKSI,
        (WELL_KNOWN_SEASONED_ISSUER, "well known seasoned issuer"),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(STAT_SHELL, (SHELL_COMPANY,), STATUTORY_BINARY_GROUP),
    CheckboxLabelSpec(
        STAT_VOLUNTARY,
        (VOLUNTARY_FILER, NOT_REQUIRED_TO_FILE_TERM),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        STAT_COMPLIANT_12_MONTHS,
        (PRECEDING_12_MONTHS_TERM, "preceding twelve months", REQUIRED_REPORTS_TERM),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        STAT_SOX_404B,
        ("404(b)", AUDITOR_ATTESTATION_TERM, "independent auditor"),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        STAT_EGC_TRANSITION_OPTOUT,
        ("extended transition", "transition period for complying"),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        STAT_ERROR_CORRECTION,
        (ERROR_CORRECTION_TERM, "error corrections"),
        STATUTORY_BINARY_GROUP,
    ),
    CheckboxLabelSpec(
        STAT_RECOVERY_ANALYSIS,
        (RECOVERY_ANALYSIS_TERM,),
        STATUTORY_BINARY_GROUP,
    ),
)

TRANSITION_REPORT_LABEL = CheckboxLabelSpec(
    "transition",
    (
        "transition report",
        "transition reports",
        "transition report pursuant",
        "transition reports pursuant",
    ),
    REPORT_PERIOD_GROUP,
    "transition",
)


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

__all__ = [
    "COMMON_CHECKBOX_LABELS",
    "STATUTORY_CHECKBOX_CONSTRAINTS",
    "CheckboxConstraint",
    "CheckboxLabelSpec",
    "CoverCheckboxSchema",
    "TRANSITION_REPORT_LABEL",
]
