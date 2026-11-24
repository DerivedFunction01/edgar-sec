"""Per-family evidence scoring over one structured table."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.core.prose_patterns import PROSE_PATTERNS
from edgar_sec.engine.tables.extraction.core.term_patterns import PATTERNS
from edgar_sec.engine.tables.extraction.core.subjects.classification import Evidence
from edgar_sec.engine.tables.extraction.seats.commitments_seat import (
    FAMILY as COMMITMENTS_FAMILY,
)
from edgar_sec.engine.tables.extraction.seats.commitments_seat import (
    evaluate_commitments_seat,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    geometry_text_from_table,
)
from edgar_sec.engine.tables.extraction.cascade.grouping import grouping_signatures
from edgar_sec.engine.tables.extraction.cascade.negative_evidence import (
    NEGATIVE_EVIDENCE,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.text.note_titles import NOTE_TITLE_SPECS
from edgar_sec.engine.tables.extraction.core.policy import ClassificationPolicy
from edgar_sec.engine.tables.extraction.core.registry import (
    IDENTITIES_BY_FAMILY,
    LABEL_EXCLUSIVITY_WEIGHT,
    LABEL_GROUP_QUOTA,
    LABEL_WEIGHT,
    LANDMARK_GROUP_QUOTA,
    LANDMARK_POINTS,
    LANDMARK_SPECS,
    LANDMARKS,
    LOCATION_POINTS,
    MATH_GROUP_QUOTA,
    NEGATIVE_GROUP_QUOTA,
    NEGATIVE_PRESENT_POINTS,
    NEGATIVE_ZERO_RATE_POINTS,
    NOTE_GROUP_QUOTA,
    PAIR_POINTS,
    PROSE_GROUP_QUOTA,
    PROSE_POINTS,
    RESIDUAL_FAMILY,
    SHAPE_BOUNDS_BY_FAMILY,
    SHAPE_ENVELOPE_POINTS,
    SHAPE_OVERAGE_PENALTY,
    STRUCTURE_GROUP_QUOTA,
    STRUCTURE_SPECS,
    TOKEN_GROUP_QUOTA,
    TOKEN_WEIGHT,
    TRIPLE_POINTS,
)
from edgar_sec.engine.tables.extraction.core.sequences import SEQUENCES
from edgar_sec.engine.tables.extraction.cascade.residue_families import (
    CONTENT_GATED_FAMILIES,
    corroborates,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.engine.tables.extraction.core.validation import (
    IdentityOutcome,
    evaluate_math,
)
from edgar_sec.foundation.text.words import word_tokens


def label_terms(labels: list[str]) -> set[str]:
    terms = set(labels)
    for label in labels:
        tokens = [token for token in word_tokens(label) if len(token) >= 3]
        terms.update(tokens)
        terms.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False))
    return terms


def prose_ngrams(text: str) -> set[str]:
    tokens = word_tokens(text)
    grams: set[str] = set()
    for size in (2, 3, 4):
        grams.update(
            " ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)
        )
    return grams


def score_family(
    family: str,
    labels: list[str],
    label_set: set[str],
    terms: set[str],
    prose: dict[str, set[str]],
    signatures: frozenset[str],
    table: TypedTable,
    policy: ClassificationPolicy,
    math_outcomes: tuple[IdentityOutcome, ...],
    form_outcomes: tuple[FormTestOutcome, ...] = (),
) -> tuple[float, list[Evidence]]:
    score = 0.0
    evidence: list[Evidence] = []
    label_hits = 0
    token_hits = 0
    for spec in PATTERNS:
        if spec.family != family:
            continue
        if spec.term not in terms:
            continue
        if spec.kind == "label" and label_hits < LABEL_GROUP_QUOTA:
            points = LABEL_WEIGHT + LABEL_EXCLUSIVITY_WEIGHT * spec.exclusivity
            label_hits += 1
        elif spec.kind == "token" and token_hits < TOKEN_GROUP_QUOTA:
            points = TOKEN_WEIGHT * (1.0 + spec.exclusivity)
            token_hits += 1
        else:
            continue
        score += points
        evidence.append(Evidence(spec.kind, spec.term, points))
    landmarks = LANDMARKS.get(family, ())
    seen = list(dict.fromkeys(label for label in labels if label in landmarks))
    for label in seen[:LANDMARK_GROUP_QUOTA]:
        score += LANDMARK_POINTS
        evidence.append(Evidence("landmark", label, LANDMARK_POINTS))
    used = min(len(seen), LANDMARK_GROUP_QUOTA)
    for spec in LANDMARK_SPECS:
        if spec.family != family or used >= LANDMARK_GROUP_QUOTA:
            continue
        if spec.label in label_set:
            used += 1
            score += spec.points
            evidence.append(Evidence("landmark", spec.label, spec.points))
    positions = {label: index for index, label in enumerate(seen)}
    for spec in SEQUENCES:
        if spec.family != family:
            continue
        if all(term in positions for term in spec.terms) and all(
            positions[a] < positions[b]
            for a, b in zip(spec.terms, spec.terms[1:], strict=False)
        ):
            points = PAIR_POINTS if len(spec.terms) == 2 else TRIPLE_POINTS
            score += points
            evidence.append(Evidence("sequence", " > ".join(spec.terms), points))
    structure_hits = 0
    for spec in STRUCTURE_SPECS:
        if spec.family != family or structure_hits >= STRUCTURE_GROUP_QUOTA:
            continue
        if spec.name in signatures:
            structure_hits += 1
            score += spec.points
            evidence.append(Evidence("structure", spec.name, spec.points))
    prose_hits: dict[str, int] = {"before": 0, "after": 0}
    for spec in PROSE_PATTERNS:
        if spec.family != family:
            continue
        if prose_hits[spec.window] >= PROSE_GROUP_QUOTA:
            continue
        if spec.ngram in prose[spec.window]:
            prose_hits[spec.window] += 1
            score += PROSE_POINTS
            evidence.append(
                Evidence("prose", f"{spec.window}: {spec.ngram}", PROSE_POINTS)
            )
    note = table.context.note
    if note is not None and note.title:
        title = normalize_text(note.title)
        note_hits = 0
        for spec in NOTE_TITLE_SPECS:
            if spec.family != family or note_hits >= NOTE_GROUP_QUOTA:
                continue
            if spec.phrase in title:
                if family in CONTENT_GATED_FAMILIES and not corroborates(
                    family, geometry_text_from_table(table)
                ):
                    evidence.append(
                        Evidence("note", f"{spec.phrase} (uncorroborated)", 0.0)
                    )
                    continue
                note_hits += 1
                score += spec.points
                evidence.append(Evidence("note", spec.phrase, spec.points))
    if family == COMMITMENTS_FAMILY:
        seat = evaluate_commitments_seat(table)
        if seat.passed:
            score += seat.points
            evidence.append(Evidence("seat", seat.detail, seat.points))
    vetoes = 0
    for spec in NEGATIVE_EVIDENCE:
        if spec.vetoed_family != family or spec.term not in label_set:
            continue
        if vetoes >= NEGATIVE_GROUP_QUOTA:
            break
        vetoes += 1
        points = (
            NEGATIVE_ZERO_RATE_POINTS
            if spec.member_presence_rate == 0
            else NEGATIVE_PRESENT_POINTS
        )
        score -= points
        evidence.append(Evidence("negative", spec.term, -points))
    bound = SHAPE_BOUNDS_BY_FAMILY.get(family)
    if bound is not None and len(table.periods) > bound.columns_p95:
        score -= SHAPE_OVERAGE_PENALTY
        evidence.append(
            Evidence(
                "shape",
                f"columns {len(table.periods)} > p95 {bound.columns_p95}",
                -SHAPE_OVERAGE_PENALTY,
            )
        )
    if bound is not None and len(table.periods) <= bound.columns_p95:
        value_rows = sum(
            1 for row in table.rows if any(v is not None for v in row.values)
        )
        if value_rows >= bound.value_rows_p5:
            score += SHAPE_ENVELOPE_POINTS
            evidence.append(
                Evidence("shape", "within shape envelope", SHAPE_ENVELOPE_POINTS)
            )
    item = table.context.section.item if table.context.section else None
    share = policy.location_share(family, item)
    if share is not None:
        points = LOCATION_POINTS * share
        score += points
        evidence.append(Evidence("location", f"{item} share {share}", points))
    spec = IDENTITIES_BY_FAMILY.get(family)
    if spec is not None:
        for outcome in math_outcomes[:MATH_GROUP_QUOTA]:
            if outcome.closed:
                score += spec.points
                evidence.append(Evidence("math", f"{spec.name} closed", spec.points))
            else:
                evidence.append(Evidence("math", f"{spec.name} failed", 0.0))
    for outcome in form_outcomes:
        if outcome.passed:
            score += outcome.points
            evidence.append(
                Evidence("form_test", f"{outcome.test_id} passed", outcome.points)
            )
        elif outcome.evaluable:
            evidence.append(Evidence("form_test", f"{outcome.test_id} failed", 0.0))
    return score, evidence


def evidence_scores(
    table: TypedTable,
    labels: list[str],
    policy: ClassificationPolicy,
    math_outcomes: tuple[IdentityOutcome, ...] | None,
) -> dict[str, tuple[float, list[Evidence]]]:
    """Score every family the cascade scores, before arbitration."""
    label_set = {label for label in labels if label}
    terms = label_terms(labels)
    prose = {
        "before": prose_ngrams(table.context.prose_before),
        "after": prose_ngrams(table.context.prose_after),
    }
    families = {spec.family for spec in PATTERNS if spec.family != RESIDUAL_FAMILY}
    families.update(LANDMARKS)
    families.update(spec.family for spec in LANDMARK_SPECS)
    families.update(spec.family for spec in NOTE_TITLE_SPECS)
    families.update(spec.family for spec in STRUCTURE_SPECS)
    # A family the stage form-tests is a family the stage scores:
    # without a scored seat its form-test outcomes are dropped and
    # it can never be named (Step 2 assignment-stage cure).
    families.update(spec.family for spec in FORM_TEST_SPECS)
    signatures = grouping_signatures(table)
    outcomes = evaluate_math(table) if math_outcomes is None else math_outcomes
    math_by_family: dict[str, list[IdentityOutcome]] = {}
    for outcome in outcomes:
        math_by_family.setdefault(outcome.family, []).append(outcome)
    form_by_family: dict[str, list[FormTestOutcome]] = {}
    for outcome in evaluate_form_tests(table):
        form_by_family.setdefault(outcome.family, []).append(outcome)
    return {
        family: score_family(
            family,
            labels,
            label_set,
            terms,
            prose,
            signatures,
            table,
            policy,
            tuple(math_by_family.get(family, ())),
            tuple(form_by_family.get(family, ())),
        )
        for family in families
    }
