"""High-performance token-level Aho-Corasick multi-pattern automaton and matcher.

Compiles vocabulary across multiple table taxonomy families, section headings,
or extraction packs into a single deterministic finite automaton (DFA) with failure transitions.
Enables O(T + matches) single-pass multi-category lexical scanning across token streams.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from defs.text.bow import tokenize
from defs.text.bow_match import tier_confidence
from defs.text.bow_types import Token

if TYPE_CHECKING:
    from defs.taxonomy.tables.specs import TableFamilySpec
    from defs.text.bow import CompiledEvidencePack, LexicalEvidencePack


@dataclass(frozen=True, slots=True)
class MatchPayload:
    """Metadata associated with a dictionary pattern match."""

    family: str
    tier_name: str
    term: str
    value: int
    is_support: bool = False
    is_exclusion: bool = False
    min_distinct_hits: int = 1
    token_length: int = 1
    case_mode: str = "fold"


@dataclass(frozen=True, slots=True)
class MatchedTerm:
    """A matched pattern instance with source position and category metadata."""

    category: str
    tier_name: str
    term: str
    token_position: int
    value: int
    is_support: bool = False
    is_exclusion: bool = False


@dataclass(frozen=True, slots=True)
class ClassificationMatch:
    """Result of classifying a text/token stream across registered categories."""

    category: str | None
    confidence: float
    score: int
    matched_terms: tuple[str, ...] = ()
    supporting_terms: tuple[str, ...] = ()
    exclusion_terms: tuple[str, ...] = ()
    reason: str = ""


@dataclass(slots=True)
class MultiPatternAutomaton:
    """Compiled Token-level Aho-Corasick state machine."""

    transitions: list[dict[str, int]] = field(default_factory=lambda: [{}])
    fail: list[int] = field(default_factory=lambda: [0])
    outputs: list[list[MatchPayload]] = field(default_factory=lambda: [[]])

    def scan_tokens(self, tokens: list[Token]) -> list[tuple[int, MatchPayload]]:
        """Scan a token sequence in a single pass and return all matches with end positions."""
        curr = 0
        matches: list[tuple[int, MatchPayload]] = []
        for pos, tok in enumerate(tokens):
            key = tok.folded
            while curr != 0 and key not in self.transitions[curr]:
                curr = self.fail[curr]
            curr = self.transitions[curr].get(key, 0)
            if self.outputs[curr]:
                for payload in self.outputs[curr]:
                    start_pos = pos - payload.token_length + 1
                    if start_pos < 0:
                        continue
                    if payload.case_mode == "exact":
                        matched_surface = " ".join(
                            t.surface for t in tokens[start_pos : pos + 1]
                        )
                        if matched_surface != payload.term:
                            continue
                    elif payload.case_mode == "lowercase":
                        if not all(
                            t.surface.islower() for t in tokens[start_pos : pos + 1]
                        ):
                            continue
                    matches.append((pos, payload))
        return matches

    def scan_family_hits(self, tokens: list[Token]) -> dict[str, dict[str, set[str]]]:
        """Scan tokens and aggregate unique matched terms by family and tier."""
        curr = 0
        family_hits: dict[str, dict[str, set[str]]] = {}
        for pos, tok in enumerate(tokens):
            key = tok.folded
            while curr != 0 and key not in self.transitions[curr]:
                curr = self.fail[curr]
            curr = self.transitions[curr].get(key, 0)
            if self.outputs[curr]:
                for payload in self.outputs[curr]:
                    start_pos = pos - payload.token_length + 1
                    if start_pos < 0:
                        continue
                    if payload.case_mode == "exact":
                        matched_surface = " ".join(
                            t.surface for t in tokens[start_pos : pos + 1]
                        )
                        if matched_surface != payload.term:
                            continue
                    elif payload.case_mode == "lowercase":
                        if not all(
                            t.surface.islower() for t in tokens[start_pos : pos + 1]
                        ):
                            continue
                    f_dict = family_hits.setdefault(payload.family, {})
                    f_dict.setdefault(payload.tier_name, set()).add(payload.term)
        return family_hits


@dataclass(frozen=True, slots=True)
class LexicalMatcher:
    """Convenient high-level interface for single-pass multi-category classification."""

    automaton: MultiPatternAutomaton
    categories: tuple[str, ...]
    tier_requirements: dict[str, dict[str, tuple[int, int, bool]]] = field(
        default_factory=dict
    )

    def _get_tokens(self, text_or_tokens: str | list[Token]) -> list[Token]:
        if isinstance(text_or_tokens, str):
            return tokenize(text_or_tokens)
        return text_or_tokens

    def has_any(
        self,
        text_or_tokens: str | list[Token],
        categories: Sequence[str] | None = None,
    ) -> bool:
        """Return True if any registered phrase (or subset of categories) matches."""
        tokens = self._get_tokens(text_or_tokens)
        if not tokens:
            return False
        cat_filter = set(categories) if categories is not None else None
        curr = 0
        for tok in tokens:
            key = tok.folded
            while curr != 0 and key not in self.automaton.transitions[curr]:
                curr = self.automaton.fail[curr]
            curr = self.automaton.transitions[curr].get(key, 0)
            if self.automaton.outputs[curr]:
                for payload in self.automaton.outputs[curr]:
                    if (not payload.is_exclusion) and (
                        cat_filter is None or payload.family in cat_filter
                    ):
                        return True

        return False

    def find_matches(
        self, text_or_tokens: str | list[Token]
    ) -> tuple[MatchedTerm, ...]:
        """Return all matched terms and metadata in token order."""
        tokens = self._get_tokens(text_or_tokens)
        if not tokens:
            return ()
        raw_matches = self.automaton.scan_tokens(tokens)
        return tuple(
            MatchedTerm(
                category=payload.family,
                tier_name=payload.tier_name,
                term=payload.term,
                token_position=pos,
                value=payload.value,
                is_support=payload.is_support,
                is_exclusion=payload.is_exclusion,
            )
            for pos, payload in raw_matches
        )

    def classify(
        self,
        text_or_tokens: str | list[Token],
        candidate_categories: Sequence[str] | None = None,
    ) -> ClassificationMatch:
        """Classify the text against all categories in a single O(T) pass."""
        tokens = self._get_tokens(text_or_tokens)
        if not tokens:
            return ClassificationMatch(category=None, confidence=0.0, score=0)

        hits_by_cat = self.automaton.scan_family_hits(tokens)
        allowed = (
            set(candidate_categories)
            if candidate_categories is not None
            else set(self.categories)
        )

        best_cat: str | None = None
        best_score = 0
        best_confidence = 0.0
        best_pos_hits: tuple[str, ...] = ()
        best_supp_hits: tuple[str, ...] = ()
        best_excl_hits: tuple[str, ...] = ()

        for cat in allowed:
            if cat not in hits_by_cat:
                continue
            cat_hits = hits_by_cat[cat]
            excls = tuple(sorted(cat_hits.get("_exclusion", ())))
            if excls:
                continue

            score = 0
            distinct_pos_count = 0
            pos_terms: list[str] = []
            supp_terms: list[str] = []

            for tier_name, terms in cat_hits.items():
                if tier_name == "_exclusion":
                    continue
                tier_info = self.tier_requirements.get(cat, {}).get(
                    tier_name, (2, 1, False)
                )
                tier_val, min_distinct, is_support = tier_info
                if len(terms) >= min_distinct:
                    if is_support:
                        supp_terms.extend(terms)
                        score += 1
                    else:
                        pos_terms.extend(terms)
                        score = max(score, tier_val)
                        distinct_pos_count += len(terms)

            if score > 0:
                conf = tier_confidence(score, distinct_pos_count)
                if conf > best_confidence or (
                    conf == best_confidence and score > best_score
                ):
                    best_cat = cat
                    best_score = score
                    best_confidence = conf
                    best_pos_hits = tuple(sorted(pos_terms))
                    best_supp_hits = tuple(sorted(supp_terms))

        if best_cat is None:
            return ClassificationMatch(
                category=None,
                confidence=0.0,
                score=0,
                reason="no matching phrases",
            )

        return ClassificationMatch(
            category=best_cat,
            confidence=best_confidence,
            score=best_score,
            matched_terms=best_pos_hits,
            supporting_terms=best_supp_hits,
            exclusion_terms=best_excl_hits,
            reason=f"matched {best_cat} with score {best_score}",
        )


def _build_automaton(
    specs_or_dicts: Sequence[Any],
) -> tuple[
    MultiPatternAutomaton, tuple[str, ...], dict[str, dict[str, tuple[int, int, bool]]]
]:
    transitions: list[dict[str, int]] = [{}]
    fail: list[int] = [0]
    outputs: list[list[MatchPayload]] = [[]]
    categories: list[str] = []
    tier_reqs: dict[str, dict[str, tuple[int, int, bool]]] = {}

    for item in specs_or_dicts:
        if isinstance(item, tuple) and len(item) == 2:
            cat_name, phrases = item
            categories.append(cat_name)
            tier_reqs[cat_name] = {"primary": (3, 1, False)}
            for phrase in phrases:
                phrase_tokens = [t.folded for t in tokenize(phrase)]
                if not phrase_tokens:
                    continue
                payload = MatchPayload(
                    family=cat_name,
                    tier_name="primary",
                    term=phrase.strip(),
                    value=3,
                    is_support=False,
                    is_exclusion=False,
                    min_distinct_hits=1,
                )

                curr = 0
                for tok in phrase_tokens:
                    if tok not in transitions[curr]:
                        new_state = len(transitions)
                        transitions.append({})
                        fail.append(0)
                        outputs.append([])
                        transitions[curr][tok] = new_state
                    curr = transitions[curr][tok]
                outputs[curr].append(payload)
            continue

        spec = item
        name = getattr(spec, "name", str(item))
        categories.append(name)
        pack = getattr(spec, "evidence_pack", spec)
        tiers = getattr(pack, "tiers", ())
        tier_reqs[name] = {}

        for tier in tiers:
            tier_reqs[name][tier.name] = (
                tier.value,
                tier.min_distinct_hits,
                tier.support,
            )
            phrases: list[tuple[str, tuple[str, ...]]] = []
            if hasattr(tier, "terms") and tier.terms:
                for term in tier.terms:
                    parts = tuple(t.folded for t in tokenize(term))
                    if parts:
                        phrases.append((term.strip(), parts))
            else:
                if hasattr(tier, "unigrams") and tier.unigrams:
                    phrases.extend((u, (u.lower(),)) for u in tier.unigrams)
                if hasattr(tier, "ngram_index") and tier.ngram_index:
                    for ngrams in tier.ngram_index.values():
                        phrases.extend(
                            (" ".join(ng), tuple(t.lower() for t in ng))
                            for ng in ngrams
                        )

            for term_clean, term_tokens in phrases:
                if not term_tokens:
                    continue
                payload = MatchPayload(
                    family=name,
                    tier_name=tier.name,
                    term=term_clean,
                    value=tier.value,
                    is_support=tier.support,
                    is_exclusion=False,
                    min_distinct_hits=tier.min_distinct_hits,
                    token_length=len(term_tokens),
                    case_mode=tier.case_mode.value
                    if hasattr(tier, "case_mode")
                    else "fold",
                )

                curr = 0
                for tok in term_tokens:
                    if tok not in transitions[curr]:
                        new_state = len(transitions)
                        transitions.append({})
                        fail.append(0)
                        outputs.append([])
                        transitions[curr][tok] = new_state
                    curr = transitions[curr][tok]
                outputs[curr].append(payload)

        excl_phrases: list[tuple[str, ...]] = []
        if hasattr(pack, "exclusions") and pack.exclusions:
            for excl in pack.exclusions:
                parts = tuple(tok.casefold() for tok in excl.strip().split() if tok)
                if parts:
                    excl_phrases.append(parts)
        for excl_tokens in excl_phrases:
            payload = MatchPayload(
                family=name,
                tier_name="_exclusion",
                term=" ".join(excl_tokens),
                value=0,
                is_support=False,
                is_exclusion=True,
                min_distinct_hits=1,
            )
            curr = 0
            for tok in excl_tokens:
                if tok not in transitions[curr]:
                    new_state = len(transitions)
                    transitions.append({})
                    fail.append(0)
                    outputs.append([])
                    transitions[curr][tok] = new_state
                curr = transitions[curr][tok]
            outputs[curr].append(payload)

    # Build BFS failure links
    queue: deque[int] = deque()
    for next_state in transitions[0].values():
        fail[next_state] = 0
        queue.append(next_state)

    while queue:
        r = queue.popleft()
        for tok, u in transitions[r].items():
            queue.append(u)
            v = fail[r]
            while v != 0 and tok not in transitions[v]:
                v = fail[v]
            if tok in transitions[v]:
                fail[u] = transitions[v][tok]
            else:
                fail[u] = 0
            if outputs[fail[u]]:
                outputs[u].extend(outputs[fail[u]])

    automaton = MultiPatternAutomaton(
        transitions=transitions, fail=fail, outputs=outputs
    )
    return automaton, tuple(categories), tier_reqs


def compile_family_automaton(
    specs: list[TableFamilySpec] | dict[str, TableFamilySpec],
) -> MultiPatternAutomaton:
    """Compile table family specs into a unified token-level Aho-Corasick automaton."""
    spec_list = list(specs.values()) if isinstance(specs, dict) else list(specs)
    automaton, _, _ = _build_automaton(spec_list)
    return automaton


def compile_lexical_matcher(
    categories: dict[str, Sequence[str]]
    | list[TableFamilySpec]
    | dict[str, TableFamilySpec]
    | Sequence[CompiledEvidencePack]
    | Sequence[LexicalEvidencePack],
) -> LexicalMatcher:
    """Create a high-level single-pass LexicalMatcher from dictionaries or evidence packs."""
    items: list[Any]
    if isinstance(categories, dict):
        # Check if dict of strings or dict of specs
        first_val = next(iter(categories.values()), None)
        if isinstance(first_val, (list, tuple)) and all(
            isinstance(x, str) for x in first_val
        ):
            items = list(categories.items())
        else:
            items = list(categories.values())
    else:
        items = list(categories)

    automaton, cats, tier_reqs = _build_automaton(items)
    return LexicalMatcher(
        automaton=automaton,
        categories=cats,
        tier_requirements=tier_reqs,
    )


__all__ = [
    "ClassificationMatch",
    "LexicalMatcher",
    "MatchPayload",
    "MatchedTerm",
    "MultiPatternAutomaton",
    "compile_family_automaton",
    "compile_lexical_matcher",
]
