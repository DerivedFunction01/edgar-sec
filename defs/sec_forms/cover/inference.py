"""Constraint-based inference for ambiguous SEC cover checkbox glyphs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from defs.sec_forms.cover.checkmark_models import (
    DEFAULT_PENALTY_SCORER,
    CheckboxCandidate,
    ConstraintViolation,
    CoverCheckmarkResult,
    HypothesisScore,
    InferenceStatus,
    PenaltyScorer,
)
from defs.taxonomy.components.cover import (
    ANNUAL_CHECKBOX_SCHEMA,
    FILER_ACCELERATED,
    FILER_EMERGING_GROWTH,
    FILER_LARGE_ACCELERATED,
    FILER_NON_ACCELERATED,
    FILER_SMALLER_REPORTING,
    QUARTERLY_CHECKBOX_SCHEMA,
    REPORT_ANNUAL,
    REPORT_QUARTERLY,
    REPORT_TRANSITION,
    STAT_COMPLIANT_12_MONTHS,
    STAT_EGC_TRANSITION_OPTOUT,
    STAT_ERROR_CORRECTION,
    STAT_RECOVERY_ANALYSIS,
    STAT_SHELL,
    STAT_SOX_404B,
    STAT_VOLUNTARY,
    STAT_WKSI,
    CheckboxConstraint,
    CoverCheckboxSchema,
)
from defs.text.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    CheckmarkDecision,
    CheckmarkScope,
)

_FILER_KEYS = (
    FILER_LARGE_ACCELERATED,
    FILER_ACCELERATED,
    FILER_NON_ACCELERATED,
    FILER_SMALLER_REPORTING,
    FILER_EMERGING_GROWTH,
)
_PRIMARY_KEYS = _FILER_KEYS[:3]
_OVERLAY_KEYS = _FILER_KEYS[3:]
_FILER_ALIASES = {
    "large accelerated filer": FILER_LARGE_ACCELERATED,
    "accelerated filer": FILER_ACCELERATED,
    "non-accelerated filer": FILER_NON_ACCELERATED,
    "smaller reporting company": FILER_SMALLER_REPORTING,
    "emerging growth company": FILER_EMERGING_GROWTH,
}
_STATUTORY_ALIASES = {
    "wksi": STAT_WKSI,
    "well-known seasoned issuer": STAT_WKSI,
    "shell": STAT_SHELL,
    "shell company": STAT_SHELL,
    "voluntary": STAT_VOLUNTARY,
    "voluntary filer": STAT_VOLUNTARY,
    "12-month compliance": STAT_COMPLIANT_12_MONTHS,
    "preceding 12 months": STAT_COMPLIANT_12_MONTHS,
    "404(b)": STAT_SOX_404B,
    "sox 404(b)": STAT_SOX_404B,
    "egc transition opt-out": STAT_EGC_TRANSITION_OPTOUT,
    "error correction": STAT_ERROR_CORRECTION,
    "recovery analysis": STAT_RECOVERY_ANALYSIS,
}


def canonical_semantic_key(value: str) -> str:
    """Canonicalize common source labels without changing unknown labels."""
    key = " ".join(value.lower().replace("_", " ").replace("-", " ").split())
    key = key.replace("non accelerated filer", "non-accelerated filer")
    return _FILER_ALIASES.get(key, _STATUTORY_ALIASES.get(key, key))


def _schema_for_family(family: str | None) -> CoverCheckboxSchema | None:
    if family is None:
        return None
    family = family.upper()
    if family in {"10-K", "20-F"}:
        return ANNUAL_CHECKBOX_SCHEMA
    if family == "10-Q":
        return QUARTERLY_CHECKBOX_SCHEMA
    return None


def _candidate_map(
    candidates: Sequence[CheckboxCandidate],
) -> tuple[dict[str, CheckboxCandidate], tuple[str, ...]]:
    values: dict[str, CheckboxCandidate] = {}
    duplicates: list[str] = []
    for candidate in candidates:
        key = canonical_semantic_key(candidate.semantic_key)
        if key in values:
            duplicates.append(key)
        else:
            values[key] = candidate
    return values, tuple(duplicates)


def _ambiguous_glyphs(candidates: Iterable[CheckboxCandidate]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            candidate.glyph for candidate in candidates if candidate.known_state is None
        )
    )


def _decode_states(
    candidates: Sequence[CheckboxCandidate],
    assignment: Mapping[str, str],
) -> dict[int, str | None]:
    return {
        index: candidate.known_state or assignment.get(candidate.glyph)
        for index, candidate in enumerate(candidates)
    }


def _logical_values(
    candidates: Sequence[CheckboxCandidate],
    decoded: Mapping[int, str | None],
    scorer: PenaltyScorer,
) -> tuple[dict[str, str], list[ConstraintViolation], list[str]]:
    grouped: dict[str, list[tuple[CheckboxCandidate, str | None]]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        key = canonical_semantic_key(candidate.question_key or candidate.semantic_key)
        grouped[key].append((candidate, decoded[index]))

    values: dict[str, str] = {}
    violations: list[ConstraintViolation] = []
    satisfied: list[str] = []
    for key, rows in grouped.items():
        yes = [state for candidate, state in rows if candidate.answer == "yes"]
        no = [state for candidate, state in rows if candidate.answer == "no"]
        if yes and no:
            yes_state, no_state = yes[0], no[0]
            if yes_state is None or no_state is None:
                continue
            if (yes_state == "checked") == (no_state == "checked"):
                violations.append(
                    ConstraintViolation(
                        name=f"binary_xor:{key}",
                        penalty=scorer.binary_xor,
                        reason="Yes and No do not have opposite states",
                    )
                )
            else:
                values[key] = "checked" if yes_state == "checked" else "unchecked"
                satisfied.append(f"binary_xor:{key}")
            continue
        known_states = [state for _, state in rows if state is not None]
        if known_states:
            values[key] = known_states[0]
    return values, violations, satisfied


def _evaluate_constraint(
    constraint: CheckboxConstraint,
    values: Mapping[str, str],
) -> tuple[ConstraintViolation | None, str | None]:
    left = values.get(constraint.left)
    right = values.get(constraint.right)
    if left is None or right is None:
        return None, None
    if constraint.relation == "not_both":
        violated = left == constraint.left_state and right == constraint.right_state
    elif constraint.relation == "implies":
        violated = left == constraint.left_state and right != constraint.right_state
    else:
        return (
            ConstraintViolation(
                name=constraint.name,
                penalty=constraint.penalty,
                reason=f"Unknown constraint relation: {constraint.relation}",
            ),
            None,
        )
    if violated:
        return (
            ConstraintViolation(
                name=constraint.name,
                penalty=constraint.penalty,
                reason=constraint.description or constraint.name,
            ),
            None,
        )
    return None, constraint.name


def _evaluate_filer(
    values: Mapping[str, str],
    scorer: PenaltyScorer,
) -> tuple[list[ConstraintViolation], list[str]]:
    if not all(key in values for key in _FILER_KEYS):
        return [], []
    violations: list[ConstraintViolation] = []
    satisfied: list[str] = []
    primary_count = sum(values[key] == "checked" for key in _PRIMARY_KEYS)
    if primary_count != 1:
        violations.append(
            ConstraintViolation(
                name="filer_primary_exactly_one",
                penalty=scorer.primary_exactly_one,
                reason=f"primary filer count is {primary_count}, expected 1",
            )
        )
    else:
        satisfied.append("filer_primary_exactly_one")
    if values[FILER_LARGE_ACCELERATED] == "checked":
        for overlay in _OVERLAY_KEYS:
            if values[overlay] == "checked":
                violations.append(
                    ConstraintViolation(
                        name=f"filer_laf_exclusion:{overlay}",
                        penalty=scorer.filer_laf_overlay,
                        reason="large accelerated filer cannot use this overlay",
                    )
                )
    if (
        values[FILER_LARGE_ACCELERATED] == "checked"
        and values[FILER_SMALLER_REPORTING] == "unchecked"
        and values[FILER_EMERGING_GROWTH] == "unchecked"
    ):
        satisfied.append("filer_laf_overlay_exclusion")
    return violations, satisfied


def _evaluate_report_period(
    candidates: Mapping[str, CheckboxCandidate],
    values: Mapping[str, str],
    family: str,
    scorer: PenaltyScorer,
) -> tuple[list[ConstraintViolation], list[str], dict[str, str]]:
    companion = (
        REPORT_ANNUAL if family.upper() in {"10-K", "20-F"} else REPORT_QUARTERLY
    )
    transition = candidates.get(REPORT_TRANSITION)
    companion_candidate = candidates.get(companion)
    if transition is None or companion_candidate is None:
        return [], [], {}
    target = REPORT_TRANSITION if transition.date_valid else companion
    violations: list[ConstraintViolation] = []
    satisfied: list[str] = []
    for key, expected in ((REPORT_TRANSITION, target), (companion, target)):
        state = values.get(key)
        if state is None:
            continue
        desired = "checked" if key == expected else "unchecked"
        if state != desired:
            direct = candidates[key].known_state is not None
            violations.append(
                ConstraintViolation(
                    name=f"direct_state:{key}" if direct else f"report_period:{key}",
                    penalty=scorer.direct_state if direct else scorer.report_period,
                    reason=f"expected {key} to be {desired}",
                )
            )
        else:
            satisfied.append(f"report_period:{key}")
    return violations, satisfied, {"selected_period": target}


def _hypotheses(glyphs: Sequence[str]) -> tuple[dict[str, str], ...]:
    if not glyphs:
        return ({},)
    if len(glyphs) > 2:
        return ()
    if len(glyphs) == 1:
        return tuple({glyphs[0]: state} for state in ("checked", "unchecked"))
    return tuple(
        {glyphs[0]: first, glyphs[1]: second}
        for first, second in (("checked", "unchecked"), ("unchecked", "checked"))
    )


def _score_candidates(
    candidates: Sequence[CheckboxCandidate],
    *,
    schema: CoverCheckboxSchema | None = None,
    family: str | None = None,
    include_filer: bool = True,
    include_report_period: bool = True,
    scorer: PenaltyScorer = DEFAULT_PENALTY_SCORER,
) -> tuple[HypothesisScore, ...]:
    glyphs = _ambiguous_glyphs(candidates)
    candidate_map, _ = _candidate_map(candidates)
    scores: list[HypothesisScore] = []
    for hypothesis in _hypotheses(glyphs):
        decoded = _decode_states(candidates, hypothesis)
        values, violations, satisfied = _logical_values(candidates, decoded, scorer)
        if include_filer and all(key in candidate_map for key in _FILER_KEYS):
            filer_violations, filer_satisfied = _evaluate_filer(values, scorer)
            violations.extend(filer_violations)
            satisfied.extend(filer_satisfied)
        for constraint in schema.constraints if schema is not None else ():
            violation, pass_name = _evaluate_constraint(constraint, values)
            if violation is not None:
                violations.append(violation)
            elif pass_name is not None:
                satisfied.append(pass_name)
        if include_report_period and family is not None:
            report_violations, report_satisfied, _ = _evaluate_report_period(
                candidate_map, values, family, scorer
            )
            violations.extend(report_violations)
            satisfied.extend(report_satisfied)
        scores.append(
            HypothesisScore(
                assignment=tuple(sorted(hypothesis.items())),
                penalty=sum(item.penalty for item in violations),
                violations=tuple(violations),
                satisfied=tuple(dict.fromkeys(satisfied)),
                states=tuple(sorted(values.items())),
            )
        )
    return tuple(scores)


def _result_for_scores(
    candidates: Sequence[CheckboxCandidate],
    scores: Sequence[HypothesisScore],
    *,
    facts: Mapping[str, str] | None = None,
) -> CoverCheckmarkResult:
    if not scores:
        return CoverCheckmarkResult(
            status=InferenceStatus.UNRESOLVED,
            diagnostics=("more_than_two_glyph_classes",),
            candidates=tuple(candidates),
        )
    best_penalty = min(score.penalty for score in scores)
    best = tuple(score for score in scores if score.penalty == best_penalty)
    if len(best) != 1:
        return CoverCheckmarkResult(
            status=InferenceStatus.UNRESOLVED,
            diagnostics=("hypotheses_tied",)
            + tuple(
                f"hypothesis_{index}_penalty={score.penalty}"
                for index, score in enumerate(scores)
            ),
            hypotheses=tuple(scores),
            candidates=tuple(candidates),
        )
    selected = best[0]
    if any(item.name.startswith("direct_state:") for item in selected.violations):
        return CoverCheckmarkResult(
            status=InferenceStatus.UNRESOLVED,
            diagnostics=("direct_state_conflict",)
            + tuple(f"violation:{item.name}" for item in selected.violations),
            hypotheses=tuple(scores),
            candidates=tuple(candidates),
        )
    assignment = dict(selected.assignment)
    decisions = tuple(
        CheckmarkDecision(
            source_token=candidate.source_token,
            canonical_token=(
                CANONICAL_CHECKED
                if assignment[candidate.glyph] == "checked"
                else CANONICAL_UNCHECKED
            ),
            state=assignment[candidate.glyph],
            scope=CheckmarkScope.COVER_CONTEXT.value,
            confidence=1.0 if selected.penalty == 0 else 0.75,
            reason="constraint_solution"
            if selected.penalty == 0
            else "soft_penalty_recovery",
            source_region=candidate.source_region,
            span=candidate.mark_span,
        )
        for candidate in candidates
        if candidate.known_state is None and candidate.glyph in assignment
    )
    diagnostics = ()
    if selected.penalty:
        diagnostics = (f"soft_penalty_recovery={selected.penalty}",) + tuple(
            f"violation:{item.name}:{item.penalty}" for item in selected.violations
        )
    return CoverCheckmarkResult(
        status=InferenceStatus.RESOLVED,
        decisions=decisions,
        facts=tuple(sorted((facts or {}).items())),
        diagnostics=diagnostics,
        hypotheses=tuple(scores),
        penalty=selected.penalty,
        candidates=tuple(candidates),
    )


_PUBLIC_SOLVER_NAMES = frozenset(
    {
        "apply_cover_checkmark_decisions",
        "extract_cover_candidates",
        "extract_table_candidates",
        "infer_cover_checkmarks",
        "solve_cover_constraints",
        "solve_filer_constraints",
        "solve_report_period",
        "solve_statutory_constraints",
        "update_table_geometries",
    }
)


def __getattr__(name: str) -> object:
    """Keep the original inference-module imports lazy after the split."""
    if name in _PUBLIC_SOLVER_NAMES:
        from defs.sec_forms.cover import (
            checkmark_candidates,
            checkmark_rewrite,
            checkmark_solver,
        )

        for module in (checkmark_candidates, checkmark_rewrite, checkmark_solver):
            if hasattr(module, name):
                return getattr(module, name)
    raise AttributeError(name)


__all__ = [
    "CheckboxCandidate",
    "ConstraintViolation",
    "CoverCheckmarkResult",
    "HypothesisScore",
    "InferenceStatus",
    "PenaltyScorer",
    "canonical_semantic_key",
]
