"""Token-boundary lexical evidence packs and the scorer that evaluates them.

An :class:`EvidenceTier` carries vocabulary plus a decision policy; a
:class:`LexicalEvidencePack` is an immutable, ordered list of those tiers. The
scorer walks the tiers once, folding satisfied tiers into a capped 0-3 decision
score with a calibrated confidence, and reports every matched term so a caller
can explain the decision. The engine is form- and domain-neutral: vocabulary
lives in the owning pack, never here.

The token and case-mode primitives are shared with the Aho-Corasick automaton in
:mod:`edgar_sec.foundation.text.automaton`; this module owns only the
tier-and-pack half of the contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .automaton import CaseMode, Token, tokenize

_TIER_VALUES = (1, 2, 3)
_MATCH_KINDS = ("unigram", "ngram")
_MAX_COMPILED_PACKS = 64


@dataclass(frozen=True, slots=True)
class CompiledTier:
    """A tier with normalized, length-grouped token indexes."""

    name: str
    priority: int
    value: int
    match_kind: str
    min_distinct_hits: int
    case_mode: CaseMode
    support: bool = False
    unigrams: frozenset[str] = frozenset()
    ngram_index: dict[int, frozenset[tuple[str, ...]]] | None = None


@dataclass(frozen=True, slots=True)
class CompiledEvidencePack:
    """A pack compiled once for reuse across many units."""

    name: str
    tiers: tuple[CompiledTier, ...]
    band_max_value: tuple[int, ...]
    exclusions: frozenset[str] = frozenset()
    automaton: object | None = None


def token_to_key(token: Token, mode: CaseMode) -> str | None:
    """Return the lookup key for a token under a case mode, or None to skip."""
    if mode is CaseMode.FOLD:
        return token.folded
    if mode is CaseMode.EXACT:
        return token.surface
    if mode is CaseMode.LOWERCASE:
        return token.surface if token.surface.islower() else None
    raise ValueError(f"unsupported case mode: {mode!r}")


def window_key(
    tokens: list[Token], start: int, length: int, mode: CaseMode
) -> str | None:
    """Build the lookup key for an n-gram window, or return None to skip."""
    keys: list[str] = []
    for index in range(length):
        key = token_to_key(tokens[start + index], mode)
        if key is None:
            return None
        keys.append(key)
    return " ".join(keys)


def match_unigrams(
    tokens: list[Token], vocab: frozenset[str], mode: object
) -> dict[str, list[int]]:
    """Return matched unigram terms and their source positions."""
    matched: dict[str, list[int]] = {}
    for position, token in enumerate(tokens):
        key = token_to_key(token, mode)
        if key is None or key not in vocab:
            continue
        matched.setdefault(key, []).append(position)
    return matched


def match_ngrams(
    tokens: list[Token],
    index_by_length: dict[int, frozenset[tuple[str, ...]]],
    mode: object,
) -> dict[tuple[str, ...], list[int]]:
    """Return matched n-gram phrases and their start positions."""
    matched: dict[tuple[str, ...], list[int]] = {}
    token_count = len(tokens)
    for length, index in index_by_length.items():
        if length > token_count:
            continue
        for start in range(token_count - length + 1):
            key = window_key(tokens, start, length, mode)
            if key is None:
                continue
            phrase = tuple(key.split(" "))
            if phrase in index:
                matched.setdefault(phrase, []).append(start)
    return matched


def band_max_values(compiled: list[CompiledTier]) -> tuple[int, ...]:
    """Return the maximum value per priority band, in priority-descending order.

    Same-priority tiers share a band; the band max is the max of its members.
    Useful as a trace signal and for upper-bound reasoning.
    """
    if not compiled:
        return ()
    bands: list[int] = []
    current_priority: int | None = None
    current_max = 0
    for tier in compiled:
        if tier.priority != current_priority:
            if current_priority is not None:
                bands.append(current_max)
            current_priority = tier.priority
            current_max = tier.value
        else:
            current_max = max(current_max, tier.value)
    if current_priority is not None:
        bands.append(current_max)
    return tuple(bands)


def tier_confidence(value: int, distinct_hits: int) -> float:
    """Calibrated confidence for a satisfied tier."""
    if value >= 3:
        return min(0.98, 0.9 + 0.02 * distinct_hits)
    if value >= 2:
        return min(0.95, 0.8 + 0.03 * distinct_hits)
    return min(0.6, 0.45 + 0.05 * distinct_hits)


def build_reason(
    score: int,
    satisfied: list[str],
    partial_strong: bool,
    exclusions: tuple[str, ...],
    pack_name: str,
) -> str:
    """Explain a score from the tiers, partial hits, and exclusions behind it."""
    if score >= 2:
        return f"satisfied tier(s) {satisfied} with decisive evidence"
    if score == 1 and satisfied:
        return f"satisfied weak tier(s) {satisfied}"
    if score == 1:
        return "partial high-confidence evidence below distinct-hit minimum"
    if exclusions:
        preview = ", ".join(exclusions[:5])
        return f"form/cover exclusion terms only: {preview}"
    return f"no lexical evidence matched in pack {pack_name!r}"


@dataclass(frozen=True, slots=True)
class EvidenceTier:
    """One ordered evidence tier owned by a form or extraction pack.

    ``priority`` orders evaluation (higher runs first). ``value`` is the
    decision strength of a satisfied tier (1, 2, or 3).
    ``min_distinct_hits`` counts distinct matched terms, not occurrences.
    ``case_mode`` selects how terms match source tokens.
    ``support`` marks corroborating evidence: a satisfied support tier adds
    its value to the score additively instead of setting it, so it can push
    a unit over the decision threshold only alongside other evidence.
    Support tiers must use ``value=1`` so support evidence alone can never
    confirm a decision.
    """

    name: str
    priority: int
    value: int
    terms: tuple[str, ...]
    match_kind: str = "unigram"
    min_distinct_hits: int = 1
    case_mode: CaseMode = CaseMode.FOLD
    support: bool = False

    def __post_init__(self) -> None:
        if self.value not in _TIER_VALUES:
            raise ValueError(f"tier value must be one of {_TIER_VALUES}: {self.value}")
        if self.support and self.value != 1:
            raise ValueError("support tiers must use value=1")
        if self.match_kind not in _MATCH_KINDS:
            raise ValueError(
                f"tier match_kind must be one of {_MATCH_KINDS}: {self.match_kind}"
            )
        if self.min_distinct_hits < 1:
            raise ValueError("tier min_distinct_hits must be >= 1")
        if isinstance(self.case_mode, str):
            try:
                object.__setattr__(self, "case_mode", CaseMode(self.case_mode))
            except ValueError as exc:
                raise ValueError(
                    f"tier case_mode must be one of {tuple(m.value for m in CaseMode)}: "
                    f"{self.case_mode!r}"
                ) from exc


@dataclass(frozen=True, slots=True)
class LexicalEvidencePack:
    """An immutable, ordered lexical evidence pack.

    ``tiers`` carry the vocabulary and per-tier decision policy. ``exclusions``
    are recorded in the score result when they appear in a unit's tokens.
    """

    name: str
    tiers: tuple[EvidenceTier, ...] = ()
    exclusion_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceContext:
    """Caller-supplied scoring context.

    ``eligible`` reflects caller-side structural policy (TOC overlap,
    protected tables, or intentional table search in extraction callers).
    ``prefix_vocab`` is diagnostic only and never affects the score.
    """

    eligible: bool = True
    unit_kind: str | None = None
    zone: str | None = None
    exclusion_reason: str = ""
    prefix_vocab: frozenset[str] = frozenset()
    min_words: int = 8


@dataclass(frozen=True, slots=True)
class EvidenceHit:
    """One matched evidence term with its occurrence trace."""

    tier: str
    term: str
    match_kind: str
    count: int
    positions: tuple[int, ...] = ()
    case_mode: str = CaseMode.FOLD.value


@dataclass(frozen=True, slots=True)
class BowScore:
    """Result of lexical evidence scoring for one unit.

    ``score`` is the capped decision score (0-3). ``support_score`` records
    the raw additive contribution of satisfied support tiers that was folded
    into ``score``; it is diagnostic and never exceeds the support tiers'
    own values.
    """

    score: int
    classification: str
    confidence: float
    hits: tuple[EvidenceHit, ...] = ()
    exclusions: tuple[str, ...] = ()
    satisfied_tiers: tuple[str, ...] = ()
    evaluated_tiers: tuple[str, ...] = ()
    short_circuited: bool = False
    novel_count: int = 0
    support_score: int = 0
    reason: str = ""


def normalize_tokens(text: str) -> list[str]:
    """Lowercase tokens from ``text``; convenience wrapper around ``tokenize``."""
    return [token.folded for token in tokenize(text)]


def _tokenize_term(term: str) -> list[Token]:
    return tokenize(term)


def _validate_term_tokens(
    term: str, tokens: list[Token], match_kind: str, case_mode: CaseMode, tier_name: str
) -> None:
    if match_kind == "unigram" and len(tokens) != 1:
        raise ValueError(
            f"tier {tier_name!r} unigram term {term!r} must tokenize to one token"
        )
    if match_kind == "ngram" and len(tokens) < 2:
        raise ValueError(
            f"tier {tier_name!r} ngram term {term!r} must tokenize to two or more tokens"
        )
    if case_mode is CaseMode.LOWERCASE:
        for token in tokens:
            if not token.surface.islower():
                raise ValueError(
                    f"tier {tier_name!r} lowercase-mode term {term!r} must be all lowercase"
                )


def _check_collision(pack: LexicalEvidencePack) -> None:
    """A folded term shape is owned by one case mode per pack."""
    folded_to_mode: dict[str, CaseMode] = {}
    for tier in pack.tiers:
        for term in tier.terms:
            for token in _tokenize_term(term):
                existing = folded_to_mode.get(token.folded)
                if existing is not None and existing != tier.case_mode:
                    raise ValueError(
                        f"term {term!r} (folded {token.folded!r}) is configured under "
                        f"multiple case modes: {existing.value!r} and "
                        f"{tier.case_mode.value!r}"
                    )
                folded_to_mode[token.folded] = tier.case_mode


def _build_compiled_tier(tier: EvidenceTier) -> CompiledTier:
    if not tier.terms:
        raise ValueError(f"tier {tier.name!r} has no terms")
    if tier.match_kind == "unigram":
        unigrams: set[str] = set()
        for term in tier.terms:
            tokens = _tokenize_term(term)
            _validate_term_tokens(term, tokens, "unigram", tier.case_mode, tier.name)
            unigrams.add(
                tokens[0].surface
                if tier.case_mode is CaseMode.EXACT
                else tokens[0].folded
            )
        return CompiledTier(
            name=tier.name,
            priority=tier.priority,
            value=tier.value,
            match_kind=tier.match_kind,
            min_distinct_hits=tier.min_distinct_hits,
            case_mode=tier.case_mode,
            support=tier.support,
            unigrams=frozenset(unigrams),
        )
    index: dict[int, set[tuple[str, ...]]] = {}
    for term in tier.terms:
        tokens = _tokenize_term(term)
        _validate_term_tokens(term, tokens, "ngram", tier.case_mode, tier.name)
        phrase = tuple(token_to_key(token, tier.case_mode) for token in tokens)
        index.setdefault(len(phrase), set()).add(phrase)
    return CompiledTier(
        name=tier.name,
        priority=tier.priority,
        value=tier.value,
        match_kind=tier.match_kind,
        min_distinct_hits=tier.min_distinct_hits,
        case_mode=tier.case_mode,
        support=tier.support,
        ngram_index={
            length: frozenset(phrases) for length, phrases in sorted(index.items())
        },
    )


@lru_cache(maxsize=_MAX_COMPILED_PACKS)
def compile_evidence_pack(pack: LexicalEvidencePack) -> CompiledEvidencePack:
    """Compile a lexical evidence pack once for fast reuse.

    The cache is keyed by pack value; equal packs share one compiled index.
    """
    _check_collision(pack)
    names: set[str] = set()
    compiled: list[CompiledTier] = []
    for tier in sorted(pack.tiers, key=lambda t: (-t.priority, -t.value, t.name)):
        if tier.name in names:
            raise ValueError(f"duplicate tier name {tier.name!r} in pack {pack.name!r}")
        names.add(tier.name)
        compiled.append(_build_compiled_tier(tier))

    from edgar_sec.foundation.text.automaton import compile_family_automaton

    automaton = compile_family_automaton([pack])

    return CompiledEvidencePack(
        name=pack.name,
        tiers=tuple(compiled),
        band_max_value=band_max_values(compiled),
        exclusions=frozenset(
            token.folded
            for term in pack.exclusion_terms
            for token in _tokenize_term(term)
        ),
        automaton=automaton,
    )


def score_tokens(
    tokens: list[Token],
    compiled: CompiledEvidencePack,
    context: EvidenceContext | None = None,
) -> BowScore:
    """Evaluate source tokens against a compiled evidence pack."""
    context = context or EvidenceContext()
    if not context.eligible:
        return BowScore(
            score=0,
            classification="no_match",
            confidence=0.0,
            reason=context.exclusion_reason or "unit is ineligible for scoring",
        )
    if len(tokens) < context.min_words:
        return BowScore(
            score=0,
            classification="no_match",
            confidence=0.0,
            reason=(
                f"unit has {len(tokens)} tokens, below minimum {context.min_words}"
            ),
        )
    if not compiled.tiers:
        return BowScore(
            score=0,
            classification="no_match",
            confidence=0.0,
            reason=f"evidence pack {compiled.name!r} has no tiers",
        )

    token_set = frozenset(token.folded for token in tokens)
    exclusions = tuple(sorted(token_set & compiled.exclusions))
    novel_count = len(token_set - context.prefix_vocab) if context.prefix_vocab else 0

    hits: list[EvidenceHit] = []
    evaluated: list[str] = []
    satisfied: list[str] = []
    score = 0
    support_score = 0
    support_confidence = 0.0
    confidence = 0.0
    partial_strong = False
    short_circuited = False

    # In-band bookkeeping: same-priority tiers form a band; the band's max
    # value is tracked so the rest of the band can short-circuit as soon
    # as any tier in it satisfies at that value.
    current_band_priority: int | None = None
    current_band_max = 0

    matched_by_tier: dict[str, dict[str, list[int]]] = {}
    if compiled.automaton is not None:
        raw_matches = compiled.automaton.scan_tokens(tokens)  # type: ignore[attr-defined]
        for pos, payload in raw_matches:
            if payload.is_exclusion:
                continue
            start_pos = pos - payload.token_length + 1
            tier_dict = matched_by_tier.setdefault(payload.tier_name, {})
            tier_dict.setdefault(payload.term, []).append(start_pos)

    for tier_index, tier in enumerate(compiled.tiers):
        if tier.priority != current_band_priority:
            current_band_priority = tier.priority
            current_band_max = tier.value
        evaluated.append(tier.name)
        if compiled.automaton is not None:
            matched = matched_by_tier.get(tier.name, {})
            tier_hits = [
                EvidenceHit(
                    tier=tier.name,
                    term=term,
                    match_kind=tier.match_kind,
                    count=len(positions),
                    positions=tuple(positions),
                    case_mode=tier.case_mode.value,
                )
                for term, positions in sorted(matched.items())
            ]
        elif tier.match_kind == "unigram":
            matched_u = match_unigrams(tokens, tier.unigrams, tier.case_mode)
            tier_hits = [
                EvidenceHit(
                    tier=tier.name,
                    term=term,
                    match_kind="unigram",
                    count=len(positions),
                    positions=tuple(positions),
                    case_mode=tier.case_mode.value,
                )
                for term, positions in sorted(matched_u.items())
            ]
        else:
            matched_n = match_ngrams(tokens, tier.ngram_index or {}, tier.case_mode)
            tier_hits = [
                EvidenceHit(
                    tier=tier.name,
                    term=" ".join(phrase),
                    match_kind="ngram",
                    count=len(positions),
                    positions=tuple(positions),
                    case_mode=tier.case_mode.value,
                )
                for phrase, positions in sorted(matched_n.items())
            ]
        hits.extend(tier_hits)
        distinct = len(tier_hits)

        if distinct >= tier.min_distinct_hits:
            satisfied.append(tier.name)
            if tier.support:
                # Support evidence is additive and can never set or raise
                # the primary score, trigger a band short-circuit, or confirm
                # a decision alone (support tiers are constrained to value=1).
                support_score += tier.value
                support_confidence = max(
                    support_confidence, tier_confidence(tier.value, distinct)
                )
            else:
                if tier.value > score:
                    score = tier.value
                    confidence = tier_confidence(tier.value, distinct)
                if score == current_band_max:
                    short_circuited = True
                    for later in compiled.tiers[tier_index + 1 :]:
                        if later.priority != current_band_priority:
                            break
                        evaluated.append(later.name)
                    break

        elif distinct and tier.value >= 2 and not tier.support:
            partial_strong = True

        if score >= 2:
            remaining = compiled.tiers[tier_index + 1 :]
            if not any(lower.value > score for lower in remaining):
                short_circuited = True
                break

    if score == 0 and partial_strong:
        score = 1

    total = min(3, score + support_score)
    if total >= 2:
        classification = "matched"
        if confidence == 0.0:
            confidence = support_confidence
    elif total == 1:
        classification = "ambiguous"
    else:
        classification = "no_match"

    if confidence == 0.0 and total == 1 and not satisfied:
        confidence = 0.3
    if confidence == 0.0 and total == 0 and exclusions:
        confidence = 0.2

    return BowScore(
        score=total,
        classification=classification,
        confidence=confidence,
        hits=tuple(hits),
        exclusions=exclusions,
        satisfied_tiers=tuple(satisfied),
        evaluated_tiers=tuple(evaluated),
        short_circuited=short_circuited,
        novel_count=novel_count,
        support_score=support_score,
        reason=build_reason(
            total, satisfied, partial_strong, exclusions, compiled.name
        ),
    )


def score_unit(
    text: str,
    pack: LexicalEvidencePack | CompiledEvidencePack,
    context: EvidenceContext | None = None,
) -> BowScore:
    """Score one unit's text against a lexical evidence pack.

    ``pack`` may be a ``LexicalEvidencePack`` (compiled and cached on first
    use) or an already-compiled pack for hot loops.
    """
    if isinstance(pack, CompiledEvidencePack):
        compiled = pack
    else:
        compiled = compile_evidence_pack(pack)
    return score_tokens(tokenize(text), compiled, context)


__all__ = [
    "BowScore",
    "CaseMode",
    "CompiledEvidencePack",
    "CompiledTier",
    "EvidenceContext",
    "EvidenceHit",
    "EvidenceTier",
    "LexicalEvidencePack",
    "Token",
    "band_max_values",
    "build_reason",
    "compile_evidence_pack",
    "match_ngrams",
    "match_unigrams",
    "normalize_tokens",
    "score_tokens",
    "score_unit",
    "tier_confidence",
    "token_to_key",
    "tokenize",
    "window_key",
]
