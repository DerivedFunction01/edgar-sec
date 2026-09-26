"""Shared token-boundary lexical evidence engine and multi-pattern automaton.

The engine is form- and domain-neutral: it consumes a ``LexicalEvidencePack``
of ordered evidence tiers and scores tokenized units. Form-specific and
extraction-specific vocabulary lives in the owning packs, never here.
"""

from __future__ import annotations

from .automaton import (
    ClassificationMatch,
    LexicalMatcher,
    MatchedTerm,
    MatchPayload,
    MultiPatternAutomaton,
    compile_family_automaton,
    compile_lexical_matcher,
)
from .engine import (
    BowScore,
    CompiledEvidencePack,
    EvidenceContext,
    EvidenceHit,
    EvidenceTier,
    LexicalEvidencePack,
    Token,
    compile_evidence_pack,
    normalize_tokens,
    score_tokens,
    score_unit,
    tokenize,
)
from .match import (
    band_max_values,
    build_reason,
    match_ngrams,
    match_unigrams,
    tier_confidence,
)
from .types import (
    CaseMode,
    CompiledTier,
    token_to_key,
    window_key,
)

__all__ = [
    "BowScore",
    "CaseMode",
    "ClassificationMatch",
    "CompiledEvidencePack",
    "CompiledTier",
    "EvidenceContext",
    "EvidenceHit",
    "EvidenceTier",
    "LexicalEvidencePack",
    "LexicalMatcher",
    "MatchPayload",
    "MatchedTerm",
    "MultiPatternAutomaton",
    "Token",
    "band_max_values",
    "build_reason",
    "compile_evidence_pack",
    "compile_family_automaton",
    "compile_lexical_matcher",
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
