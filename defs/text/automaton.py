"""High-performance token-level Aho-Corasick multi-pattern automaton.

Compiles vocabulary across multiple table taxonomy families or extraction packs
into a single deterministic finite automaton (DFA) with failure transitions.
Enables O(T + matches) single-pass multi-family lexical scanning across token streams.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from defs.taxonomy.tables.specs import TableFamilySpec
    from defs.text.bow_types import Token


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
                    matches.append((pos, payload))
        return matches

    def scan_family_hits(
        self, tokens: list[Token]
    ) -> dict[str, dict[str, set[str]]]:
        """Scan tokens and aggregate unique matched terms by family and tier."""
        curr = 0
        family_hits: dict[str, dict[str, set[str]]] = {}
        for tok in tokens:
            key = tok.folded
            while curr != 0 and key not in self.transitions[curr]:
                curr = self.fail[curr]
            curr = self.transitions[curr].get(key, 0)
            if self.outputs[curr]:
                for payload in self.outputs[curr]:
                    f_dict = family_hits.setdefault(payload.family, {})
                    f_dict.setdefault(payload.tier_name, set()).add(payload.term)
        return family_hits


def compile_family_automaton(
    specs: list[TableFamilySpec] | dict[str, TableFamilySpec],
) -> MultiPatternAutomaton:
    """Compile table family specs into a unified token-level Aho-Corasick automaton."""
    spec_list = list(specs.values()) if isinstance(specs, dict) else specs

    transitions: list[dict[str, int]] = [{}]
    fail: list[int] = [0]
    outputs: list[list[MatchPayload]] = [[]]

    for spec in spec_list:
        pack = spec.evidence_pack
        for tier in pack.tiers:
            # Handle CompiledTier or EvidenceTier
            phrases: list[tuple[str, ...]] = []
            if hasattr(tier, "unigrams") and tier.unigrams:
                phrases.extend((u,) for u in tier.unigrams)
            if hasattr(tier, "ngram_index") and tier.ngram_index:
                for ngrams in tier.ngram_index.values():
                    phrases.extend(ngrams)
            if hasattr(tier, "terms") and tier.terms:
                for term in tier.terms:
                    parts = tuple(tok.casefold() for tok in term.strip().split() if tok)
                    if parts:
                        phrases.append(parts)

            for term_tokens in phrases:
                if not term_tokens:
                    continue
                term_clean = " ".join(term_tokens)

                payload = MatchPayload(
                    family=spec.name,
                    tier_name=tier.name,
                    term=term_clean,
                    value=tier.value,
                    is_support=tier.support,
                    is_exclusion=False,
                    min_distinct_hits=tier.min_distinct_hits,
                )

                # Insert into trie
                curr = 0
                for tok in term_tokens:
                    tok_key = tok.casefold()
                    if tok_key not in transitions[curr]:
                        new_state = len(transitions)
                        transitions.append({})
                        fail.append(0)
                        outputs.append([])
                        transitions[curr][tok_key] = new_state
                    curr = transitions[curr][tok_key]
                outputs[curr].append(payload)

        # Also compile exclusion terms if present
        excl_phrases: list[tuple[str, ...]] = []
        if hasattr(pack, "exclusions") and pack.exclusions:
            for excl in pack.exclusions:
                parts = tuple(tok.casefold() for tok in excl.strip().split() if tok)
                if parts:
                    excl_phrases.append(parts)

        for excl_tokens in excl_phrases:
            payload = MatchPayload(
                family=spec.name,
                tier_name="_exclusion",
                term=" ".join(excl_tokens),
                value=0,
                is_support=False,
                is_exclusion=True,
                min_distinct_hits=1,
            )
            curr = 0
            for tok in excl_tokens:
                tok_key = tok.casefold()
                if tok_key not in transitions[curr]:
                    new_state = len(transitions)
                    transitions.append({})
                    fail.append(0)
                    outputs.append([])
                    transitions[curr][tok_key] = new_state
                curr = transitions[curr][tok_key]
            outputs[curr].append(payload)


    # Step 2: Build BFS failure links and output chains
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

    return MultiPatternAutomaton(transitions=transitions, fail=fail, outputs=outputs)


__all__ = [
    "MatchPayload",
    "MultiPatternAutomaton",
    "compile_family_automaton",
]
