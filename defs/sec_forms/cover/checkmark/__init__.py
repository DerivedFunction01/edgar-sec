"""Cover checkbox extraction, inference, and rewrite package.

Re-exports the full public API so existing imports from
``defs.sec_forms.cover`` continue to work unchanged after the module
was split into this package.
"""

from __future__ import annotations

from defs.sec_forms.cover.checkmark.candidates import (
    extract_cover_candidates,
    extract_table_candidates,
)
from defs.sec_forms.cover.checkmark.frames import build_masked_offset_translator
from defs.sec_forms.cover.checkmark.models import (
    DEFAULT_PENALTY_SCORER,
    CheckboxCandidate,
    ConstraintViolation,
    CoverCheckmarkResult,
    HypothesisScore,
    InferenceStatus,
    PenaltyScorer,
)
from defs.sec_forms.cover.checkmark.rewrite import (
    apply_cover_checkmark_decisions,
    update_table_geometries,
)
from defs.sec_forms.cover.checkmark.schemas import (
    ANNUAL_CHECKBOX_SCHEMA,
    QUARTERLY_CHECKBOX_SCHEMA,
    STATUTORY_CHECKBOX_CONSTRAINTS,
    CheckboxConstraint,
    CoverCheckboxSchema,
)
from defs.sec_forms.cover.checkmark.solver import (
    infer_cover_checkmarks,
    solve_cover_constraints,
    solve_filer_constraints,
    solve_report_period,
    solve_statutory_constraints,
)
from defs.sec_forms.cover.checkmark.yes_no_pairs import (
    YES_NO_LINE_RE,
    YES_NO_WORD_RE,
    normalize_yes_no_pair_line,
    normalize_yes_no_pairs,
)

__all__ = [
    "ANNUAL_CHECKBOX_SCHEMA",
    "DEFAULT_PENALTY_SCORER",
    "QUARTERLY_CHECKBOX_SCHEMA",
    "STATUTORY_CHECKBOX_CONSTRAINTS",
    "YES_NO_LINE_RE",
    "YES_NO_WORD_RE",
    "CheckboxCandidate",
    "CheckboxConstraint",
    "ConstraintViolation",
    "CoverCheckboxSchema",
    "CoverCheckmarkResult",
    "HypothesisScore",
    "InferenceStatus",
    "PenaltyScorer",
    "apply_cover_checkmark_decisions",
    "build_masked_offset_translator",
    "extract_cover_candidates",
    "extract_table_candidates",
    "infer_cover_checkmarks",
    "normalize_yes_no_pair_line",
    "normalize_yes_no_pairs",
    "solve_cover_constraints",
    "solve_filer_constraints",
    "solve_report_period",
    "solve_statutory_constraints",
    "update_table_geometries",
]
