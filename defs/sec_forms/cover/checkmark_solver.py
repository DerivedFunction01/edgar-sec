"""Public cover checkbox solver entry points."""

from __future__ import annotations

from collections.abc import Sequence

from defs.sec_forms.cover.checkmark_candidates import extract_cover_candidates
from defs.sec_forms.cover.checkmark_models import (
    DEFAULT_PENALTY_SCORER,
    CheckboxCandidate,
    CoverCheckmarkResult,
    InferenceStatus,
    PenaltyScorer,
)
from defs.sec_forms.cover.checkmark_rewrite import (
    apply_cover_checkmark_decisions,
    update_table_geometries,
)
from defs.sec_forms.cover.inference import (
    _FILER_KEYS,
    _candidate_map,
    _result_for_scores,
    _schema_for_family,
    _score_candidates,
)
from defs.sec_forms.cover.models import CoverBoundary
from defs.taxonomy.components.cover import (
    FILER_STATUS_GROUP,
    REPORT_ANNUAL,
    REPORT_PERIOD_GROUP,
    REPORT_QUARTERLY,
    REPORT_TRANSITION,
    STATUTORY_BINARY_GROUP,
    CoverCheckboxSchema,
)


def solve_filer_constraints(
    candidates: Sequence[CheckboxCandidate],
    *,
    scorer: PenaltyScorer = DEFAULT_PENALTY_SCORER,
) -> CoverCheckmarkResult:
    """Resolve the primary filer triplet and independent overlay pair."""
    candidate_map, duplicates = _candidate_map(candidates)
    if duplicates:
        return CoverCheckmarkResult(
            status=InferenceStatus.UNRESOLVED,
            diagnostics=(f"duplicate_semantic_rows:{','.join(duplicates)}",),
        )
    if not all(key in candidate_map for key in _FILER_KEYS):
        return CoverCheckmarkResult(
            status=InferenceStatus.ABSENT,
            diagnostics=("filer_group_incomplete",),
        )
    scores = _score_candidates(
        candidates,
        include_filer=True,
        include_report_period=False,
        scorer=scorer,
    )
    return _result_for_scores(candidates, scores)


def solve_statutory_constraints(
    candidates: Sequence[CheckboxCandidate],
    *,
    schema: CoverCheckboxSchema,
    scorer: PenaltyScorer = DEFAULT_PENALTY_SCORER,
) -> CoverCheckmarkResult:
    """Resolve form-scoped Yes/No and statutory Boolean relationships."""
    if STATUTORY_BINARY_GROUP not in schema.groups:
        return CoverCheckmarkResult(status=InferenceStatus.NOT_APPLICABLE)
    if not candidates:
        return CoverCheckmarkResult(status=InferenceStatus.ABSENT)
    scores = _score_candidates(
        candidates,
        schema=schema,
        include_filer=False,
        include_report_period=False,
        scorer=scorer,
    )
    return _result_for_scores(candidates, scores)


def solve_report_period(
    candidates: Sequence[CheckboxCandidate],
    *,
    family: str,
    scorer: PenaltyScorer = DEFAULT_PENALTY_SCORER,
) -> CoverCheckmarkResult:
    """Resolve annual/quarterly versus transition source marks."""
    family = family.upper()
    if family not in {"10-K", "20-F", "10-Q"}:
        return CoverCheckmarkResult(status=InferenceStatus.NOT_APPLICABLE)
    companion = REPORT_ANNUAL if family in {"10-K", "20-F"} else REPORT_QUARTERLY
    candidate_map, duplicates = _candidate_map(candidates)
    if (
        duplicates
        or REPORT_TRANSITION not in candidate_map
        or companion not in candidate_map
    ):
        return CoverCheckmarkResult(status=InferenceStatus.ABSENT)
    target = (
        REPORT_TRANSITION if candidate_map[REPORT_TRANSITION].date_valid else companion
    )
    scores = _score_candidates(
        candidates,
        family=family,
        include_filer=False,
        include_report_period=True,
        scorer=scorer,
    )
    return _result_for_scores(candidates, scores, facts={"selected_period": target})


def solve_cover_constraints(
    candidates: Sequence[CheckboxCandidate],
    *,
    family: str,
    schema: CoverCheckboxSchema | None = None,
    boundary: CoverBoundary | None = None,
    scorer: PenaltyScorer = DEFAULT_PENALTY_SCORER,
) -> CoverCheckmarkResult:
    """Run all applicable cover constraint groups with soft penalties."""
    schema = schema or _schema_for_family(family)
    if schema is None or boundary is not None and boundary.end_line is None:
        return CoverCheckmarkResult(status=InferenceStatus.NOT_APPLICABLE)
    if not candidates:
        return CoverCheckmarkResult(status=InferenceStatus.ABSENT)
    scores = _score_candidates(
        candidates,
        schema=schema,
        family=family,
        include_filer=FILER_STATUS_GROUP in schema.groups,
        include_report_period=REPORT_PERIOD_GROUP in schema.groups,
        scorer=scorer,
    )
    candidate_map, _ = _candidate_map(candidates)
    companion = (
        REPORT_ANNUAL if family.upper() in {"10-K", "20-F"} else REPORT_QUARTERLY
    )
    transition = candidate_map.get(REPORT_TRANSITION)
    facts = {}
    if transition is not None and companion in candidate_map:
        facts["selected_period"] = (
            REPORT_TRANSITION if transition.date_valid else companion
        )
    return _result_for_scores(candidates, scores, facts=facts)


def infer_cover_checkmarks(
    text: str,
    boundary: CoverBoundary,
    *,
    family: str,
    table_geometries: Sequence[object] = (),
    schema: CoverCheckboxSchema | None = None,
) -> CoverCheckmarkResult:
    """Extract and solve all active cover checkbox groups."""
    schema = schema or _schema_for_family(family)
    if schema is None or boundary.end_line is None:
        return CoverCheckmarkResult(status=InferenceStatus.NOT_APPLICABLE)
    candidates = extract_cover_candidates(
        text,
        boundary,
        family=family,
        table_geometries=table_geometries,
    )
    if not candidates:
        return CoverCheckmarkResult(status=InferenceStatus.ABSENT)
    return solve_cover_constraints(
        candidates,
        family=family,
        schema=schema,
        boundary=boundary,
    )


__all__ = [
    "apply_cover_checkmark_decisions",
    "infer_cover_checkmarks",
    "solve_cover_constraints",
    "solve_filer_constraints",
    "solve_report_period",
    "solve_statutory_constraints",
    "update_table_geometries",
]
