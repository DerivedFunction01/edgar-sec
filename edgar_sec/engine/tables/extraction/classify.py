"""The classification cascade over one structured table."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from edgar_sec.engine.tables.extraction.calibration import (
    PATTERNS,
    PROSE_PATTERNS,
)
from edgar_sec.engine.tables.extraction.grouping import grouping_signatures
from edgar_sec.engine.tables.extraction.negative_evidence import NEGATIVE_EVIDENCE
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.note_titles import NOTE_TITLE_SPECS
from edgar_sec.engine.tables.extraction.policy import (
    Anchor,
    ClassificationPolicy,
    LabelRule,
    default_policy,
)
from edgar_sec.engine.tables.extraction.registry import (
    ASSIGNMENT_FLOOR,
    CONTEXT_ANCHOR_MIN_SCORE,
    CORE_FAMILIES,
    FAMILY_PRIORITY,
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
    SATELLITE_FAMILIES,
    SEQUENCES,
    SHAPE_BOUNDS_BY_FAMILY,
    SHAPE_ENVELOPE_POINTS,
    SHAPE_OVERAGE_PENALTY,
    STRUCTURE_GROUP_QUOTA,
    STRUCTURE_SPECS,
    TOKEN_GROUP_QUOTA,
    TOKEN_WEIGHT,
    TRIPLE_POINTS,
)
from edgar_sec.engine.tables.extraction.regions import Region, effective_regions
from edgar_sec.engine.tables.extraction.typed_rows import RowKind, TypedTable
from edgar_sec.engine.tables.extraction.validation import (
    IdentityOutcome,
    evaluate_math,
)
from edgar_sec.foundation.text.words import word_tokens

_HEADING_MAX_CHARS = 90
_HEADING_TAIL_LINES = 3


class TableKind(Enum):
    """The structural kind a classified table carries."""

    STATEMENT = "statement"
    NOTE_DETAIL = "note_detail"
    PARENTHETICAL = "parenthetical"


@dataclass(frozen=True, slots=True)
class Evidence:
    """One scored contribution to a classification."""

    group: str
    detail: str
    points: float


@dataclass(frozen=True, slots=True)
class Classification:
    """A family decision with flavor, kind, and its evidence trail."""

    family: str
    flavor: str | None
    kind: TableKind
    tier: str
    score: float
    evidence: tuple[Evidence, ...]


def _label_terms(labels: list[str]) -> set[str]:
    terms = set(labels)
    for label in labels:
        tokens = [token for token in word_tokens(label) if len(token) >= 3]
        terms.update(tokens)
        terms.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False))
    return terms


def _prose_ngrams(text: str) -> set[str]:
    tokens = word_tokens(text)
    grams: set[str] = set()
    for size in (2, 3, 4):
        grams.update(
            " ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)
        )
    return grams


def _caption_text(table: TypedTable) -> str:
    parts = list(table.context.caption_stack)
    parts.extend(table.caption.titles)
    parts.extend(period.label for period in table.periods if period.label is not None)
    return " | ".join(normalize_text(part) for part in parts)


def _heading_text(table: TypedTable) -> str:
    lines = [
        normalize_text(line)
        for line in table.context.prose_before.splitlines()
        if line.strip()
    ]
    tail = [
        line for line in lines[-_HEADING_TAIL_LINES:] if len(line) <= _HEADING_MAX_CHARS
    ]
    return " | ".join(tail)


def _rule_matches(rule: Anchor | LabelRule, table: TypedTable) -> str | None:
    labels = [normalize_text(row.label) for row in table.rows]
    label_set = {label for label in labels if label}
    if isinstance(rule, LabelRule):
        if any(
            not any(needle in label for label in label_set) for needle in rule.required
        ):
            return None
        if rule.together and not any(
            all(needle in label for needle in rule.together) for label in label_set
        ):
            return None
        if rule.any_of and not any(
            needle in label for label in label_set for needle in rule.any_of
        ):
            return None
        return "label_rule"
    texts = []
    if "caption" in rule.sources:
        texts.append(_caption_text(table))
    if "heading" in rule.sources:
        texts.append(_heading_text(table))
    joined = " | ".join(texts)
    if any(normalize_text(phrase) in joined for phrase in rule.phrases):
        return "anchor"
    return None


def _flavor(family: str, labels: list[str], table: TypedTable) -> str | None:
    label_set = {label for label in labels if label}

    def has(*needles: str) -> bool:
        return any(needle in label for label in label_set for needle in needles)

    if family == "balance_sheet":
        if has("current assets") and has("current liabilities"):
            return "classified"
        return "unclassified"
    if family == "income_statement":
        if has("gross profit", "gross margin"):
            return "multi_step"
        return "single_step"
    if family == "cash_flow":
        if has("adjustments to reconcile"):
            return "indirect"
        valued = [
            normalize_text(row.label)
            for row in table.rows
            if any(value is not None for value in row.values)
        ]
        if valued and valued[0].startswith(("net income", "net loss")):
            return "indirect"
        return None
    return None


def _kind(family: str, table: TypedTable) -> TableKind:
    rows = table.rows
    if rows:
        parenthetical = sum(1 for row in rows if row.kind is RowKind.PARENTHETICAL)
        if parenthetical * 2 >= len(rows):
            return TableKind.PARENTHETICAL
    if family in CORE_FAMILIES:
        return TableKind.STATEMENT
    if table.context.note is not None:
        return TableKind.NOTE_DETAIL
    return TableKind.STATEMENT


def _finish(
    family: str,
    tier: str,
    score: float,
    evidence: list[Evidence],
    labels: list[str],
    table: TypedTable,
) -> Classification:
    return Classification(
        family=family,
        flavor=_flavor(family, labels, table),
        kind=_kind(family, table),
        tier=tier,
        score=score,
        evidence=tuple(evidence),
    )


def _score_family(
    family: str,
    labels: list[str],
    label_set: set[str],
    terms: set[str],
    prose: dict[str, set[str]],
    signatures: frozenset[str],
    table: TypedTable,
    policy: ClassificationPolicy,
    math_outcomes: tuple[IdentityOutcome, ...],
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
                note_hits += 1
                score += spec.points
                evidence.append(Evidence("note", spec.phrase, spec.points))
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
    return score, evidence


def _evidence_scores(
    table: TypedTable,
    labels: list[str],
    policy: ClassificationPolicy,
    math_outcomes: tuple[IdentityOutcome, ...] | None,
) -> dict[str, tuple[float, list[Evidence]]]:
    """Score every family the cascade scores, before arbitration."""
    label_set = {label for label in labels if label}
    terms = _label_terms(labels)
    prose = {
        "before": _prose_ngrams(table.context.prose_before),
        "after": _prose_ngrams(table.context.prose_after),
    }
    families = {spec.family for spec in PATTERNS if spec.family != RESIDUAL_FAMILY}
    families.update(LANDMARKS)
    families.update(spec.family for spec in LANDMARK_SPECS)
    families.update(spec.family for spec in NOTE_TITLE_SPECS)
    families.update(spec.family for spec in STRUCTURE_SPECS)
    signatures = grouping_signatures(table)
    outcomes = evaluate_math(table) if math_outcomes is None else math_outcomes
    math_by_family: dict[str, list[IdentityOutcome]] = {}
    for outcome in outcomes:
        math_by_family.setdefault(outcome.family, []).append(outcome)
    return {
        family: _score_family(
            family,
            labels,
            label_set,
            terms,
            prose,
            signatures,
            table,
            policy,
            tuple(math_by_family.get(family, ())),
        )
        for family in families
    }


def candidate_scores(
    table: TypedTable,
    policy: ClassificationPolicy | None = None,
    math_outcomes: tuple[IdentityOutcome, ...] | None = None,
) -> dict[str, tuple[float, tuple[Evidence, ...]]]:
    """Every scored family's points and evidence, before arbitration."""
    policy = policy if policy is not None else default_policy()
    labels = [normalize_text(row.label) for row in table.rows]
    scored = _evidence_scores(table, labels, policy, math_outcomes)
    return {
        family: (score, tuple(evidence)) for family, (score, evidence) in scored.items()
    }


def classify_table(
    table: TypedTable,
    policy: ClassificationPolicy | None = None,
    math_outcomes: tuple[IdentityOutcome, ...] | None = None,
) -> Classification:
    """Classify one structured table through the ordered cascade.

    Precomputed math outcomes may be supplied by callers that evaluate
    identities once per document; None evaluates them for this table.
    """
    policy = policy if policy is not None else default_policy()
    labels = [normalize_text(row.label) for row in table.rows]
    section = table.context.section
    base = [
        Evidence(
            "context",
            f"section={section.item if section else None} "
            f"note={table.context.note is not None}",
            0.0,
        )
    ]
    if table.context.region == Region.SIGNATURE.value:
        evidence = base + [
            Evidence("context", "signature region: not a statement candidate", 0.0)
        ]
        return _finish(RESIDUAL_FAMILY, "region", 0.0, evidence, labels, table)
    for rule in policy.specific:
        matched = _rule_matches(rule, table)
        if matched is not None:
            evidence = base + [Evidence(matched, rule.family, 0.0)]
            return _finish(rule.family, "specific", 0.0, evidence, labels, table)
    scored = _evidence_scores(table, labels, policy, math_outcomes)
    winner = min(
        scored,
        key=lambda family: (-scored[family][0], FAMILY_PRIORITY.index(family)),
    )
    score, evidence = scored[winner]
    if score >= ASSIGNMENT_FLOOR:
        return _finish(winner, "evidence", score, base + evidence, labels, table)
    residual = base + [
        Evidence(
            "residual",
            f"best {winner} at {score:.2f} below floor {ASSIGNMENT_FLOOR}",
            0.0,
        )
    ]
    return _finish(RESIDUAL_FAMILY, "residual", score, residual, labels, table)


def _context_base(table: TypedTable) -> list[Evidence]:
    section = table.context.section
    return [
        Evidence(
            "context",
            f"section={section.item if section else None} "
            f"note={table.context.note is not None}",
            0.0,
        )
    ]


def _refinish(
    table: TypedTable,
    scores: dict[str, float],
    evidence: dict[str, tuple[Evidence, ...]],
    marker: Evidence,
) -> Classification:
    """Re-arbitrate one table over adjusted filing-level scores."""
    labels = [normalize_text(row.label) for row in table.rows]
    winner = min(
        scores,
        key=lambda family: (-scores[family], FAMILY_PRIORITY.index(family)),
    )
    score = scores[winner]
    base = _context_base(table)
    if score >= ASSIGNMENT_FLOOR:
        trail = base + list(evidence.get(winner, ())) + [marker]
        return _finish(winner, "evidence", score, trail, labels, table)
    trail = base + [
        Evidence(
            "residual",
            f"best {winner} at {score:.2f} below floor {ASSIGNMENT_FLOOR}",
            0.0,
        ),
        marker,
    ]
    return _finish(RESIDUAL_FAMILY, "residual", score, trail, labels, table)


def classify_filing(
    tables: list[TypedTable] | tuple[TypedTable, ...],
    policy: ClassificationPolicy | None = None,
    math_outcomes: list[tuple[IdentityOutcome, ...]] | None = None,
) -> tuple[list[Classification], list[dict[str, float]]]:
    """Classify one filing's tables with the constellation pass.

    A satellite family's win before the filing's first confident core
    anchor loses that candidacy and is re-arbitrated without it.
    """
    policy = policy if policy is not None else default_policy()
    results: list[Classification] = []
    scored: list[dict[str, tuple[float, tuple[Evidence, ...]]]] = []
    for position, table in enumerate(tables):
        outcomes = None if math_outcomes is None else math_outcomes[position]
        results.append(classify_table(table, policy, math_outcomes=outcomes))
        scored.append(candidate_scores(table, policy, math_outcomes=outcomes))
    regions = effective_regions([table.context for table in tables])
    for position, region in enumerate(regions):
        if region != Region.SIGNATURE.value:
            continue
        table = tables[position]
        labels = [normalize_text(row.label) for row in table.rows]
        marker = Evidence("context", "signature region: not a statement candidate", 0.0)
        results[position] = _finish(
            RESIDUAL_FAMILY,
            "region",
            0.0,
            _context_base(table) + [marker],
            labels,
            table,
        )
        scored[position] = {}
    anchors = [
        position
        for position, result in enumerate(results)
        if result.family in CORE_FAMILIES
        and (result.tier == "specific" or result.score >= CONTEXT_ANCHOR_MIN_SCORE)
    ]
    scores: list[dict[str, float]] = [
        {family: score for family, (score, _) in entry.items()} for entry in scored
    ]
    if anchors:
        first_anchor = min(anchors)
        for position, result in enumerate(results):
            if position >= first_anchor or result.tier == "specific":
                continue
            if result.family not in SATELLITE_FAMILIES:
                continue
            adjusted = dict(scores[position])
            adjusted[result.family] = 0.0
            evidence = {
                family: trail for family, (_, trail) in scored[position].items()
            }
            marker = Evidence(
                "context",
                f"{result.family} candidacy precedes the first statement anchor",
                0.0,
            )
            results[position] = _refinish(tables[position], adjusted, evidence, marker)
            scores[position] = adjusted
    return results, scores
