"""Shared token-boundary lexical evidence engine.

The engine is form- and domain-neutral: it consumes a ``LexicalEvidencePack``
of ordered evidence tiers and scores tokenized units. Form-specific and
extraction-specific vocabulary lives in the owning packs, never here.

"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from defs.text.bow_match import (
    band_max_values,
    build_reason,
    match_ngrams,
    match_unigrams,
    tier_confidence,
)
from defs.text.bow_types import CaseMode, CompiledTier, Token, token_to_key

_DASH_CHARS = "-\u2010\u2011\u2012\u2013\u2014\u2212"
_DASH_TRANSLATION = str.maketrans({char: " " for char in _DASH_CHARS})
_TOKEN_RE = re.compile(r"[A-Za-z0-9'\-]+")
_TIER_VALUES = (1, 2, 3)
_MATCH_KINDS = ("unigram", "ngram")
_MAX_COMPILED_PACKS = 64


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


@dataclass(frozen=True, slots=True)
class CompiledEvidencePack:
    """A pack compiled once for reuse across many units."""

    name: str
    tiers: tuple[CompiledTier, ...]
    band_max_value: tuple[int, ...]
    exclusions: frozenset[str] = frozenset()


def tokenize(text: str) -> list[Token]:
    """Tokenize source text once, keeping both surface and folded views."""
    if not text:
        return []
    translated = text.translate(_DASH_TRANSLATION)
    tokens: list[Token] = []
    for match in _TOKEN_RE.finditer(translated):
        surface = match.group(0)
        if not surface:
            continue
        tokens.append(
            Token(
                surface=surface,
                folded=surface.lower(),
                start=match.start(),
                end=match.end(),
            )
        )
    return tokens


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
    return CompiledEvidencePack(
        name=pack.name,
        tiers=tuple(compiled),
        band_max_value=band_max_values(compiled),
        exclusions=frozenset(
            token.folded
            for term in pack.exclusion_terms
            for token in _tokenize_term(term)
        ),
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

    for tier_index, tier in enumerate(compiled.tiers):
        if tier.priority != current_band_priority:
            current_band_priority = tier.priority
            current_band_max = tier.value
        evaluated.append(tier.name)
        if tier.match_kind == "unigram":
            matched = match_unigrams(tokens, tier.unigrams, tier.case_mode)
            tier_hits = [
                EvidenceHit(
                    tier=tier.name,
                    term=term,
                    match_kind="unigram",
                    count=len(positions),
                    positions=tuple(positions),
                    case_mode=tier.case_mode.value,
                )
                for term, positions in sorted(matched.items())
            ]
        else:
            matched = match_ngrams(tokens, tier.ngram_index or {}, tier.case_mode)
            tier_hits = [
                EvidenceHit(
                    tier=tier.name,
                    term=" ".join(phrase),
                    match_kind="ngram",
                    count=len(positions),
                    positions=tuple(positions),
                    case_mode=tier.case_mode.value,
                )
                for phrase, positions in sorted(matched.items())
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
    "compile_evidence_pack",
    "normalize_tokens",
    "score_tokens",
    "score_unit",
    "tokenize",
]
