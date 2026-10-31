"""Declarative token lexicon: typed phrase claims and phrase scanning."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

CLAIM_KINDS = ("head", "modifier", "boundary", "relation", "indexical")
HEAD_CLAIM_CLASSES = ("PRIMARY", "INSTRUMENT", "TAIL", "COMPOUND_QUALIFIER")
RELATION_KINDS = ("NET_OF", "EXCLUDING", "INCLUDING")


@dataclass(frozen=True, slots=True)
class LexiconEntry:
    """A lexical claim binding a token phrase to a typed coordinate payload."""

    phrase: tuple[str, ...]
    claim: str
    head: str | None = None
    claim_class: str | None = None
    carriage: tuple[str, ...] = ()
    atom: str | None = None
    also_asserts: tuple[str, ...] = ()
    relation: str | None = None
    operand_mods: tuple[str, ...] = ()
    projection: tuple[str, ...] = ()
    direction: float | None = None
    indexical: str | None = None
    scope_next: tuple[str, ...] = ()
    temporal_pattern: str | None = None
    coexists_with: tuple[str, ...] = ()
    requires_evidence: bool = False
    sub_identity: bool = True
    protect_far_head: bool = False
    sub_suppress: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LexiconEntry:
        """Construct a LexiconEntry from its v2 dictionary format."""
        raw_phrase = data.get("phrase", [])
        if isinstance(raw_phrase, str):
            phrase = tuple(p.lower() for p in raw_phrase.split())
        else:
            phrase = tuple(str(p).lower() for p in raw_phrase)
        claim = str(data.get("claim", "")).lower()
        if claim not in CLAIM_KINDS:
            raise ValueError(f"lexicon entry {phrase} has unknown claim {claim!r}")
        claim_class = data.get("claim_class")
        if claim == "head":
            if not data.get("head"):
                raise ValueError(f"head claim {phrase} names no head")
            if claim_class not in HEAD_CLAIM_CLASSES:
                raise ValueError(
                    f"head claim {phrase} must declare a claim class"
                    f" (one of {HEAD_CLAIM_CLASSES})"
                )
        relation = data.get("relation")
        if claim == "relation" and relation not in RELATION_KINDS:
            raise ValueError(f"relation claim {phrase} has unknown kind {relation!r}")

        def _ids(key: str) -> tuple[str, ...]:
            raw = data.get(key, ())
            return tuple(str(m) for m in raw) if isinstance(raw, (list, tuple)) else ()

        return cls(
            phrase=phrase,
            claim=claim,
            head=data.get("head"),
            claim_class=claim_class,
            carriage=_ids("carriage"),
            atom=data.get("atom"),
            also_asserts=_ids("also_asserts"),
            relation=relation,
            operand_mods=_ids("operand_mods"),
            projection=_ids("projection"),
            direction=float(data["direction"]) if "direction" in data else None,
            indexical=data.get("indexical"),
            scope_next=tuple(str(t).lower() for t in data.get("scope_next", ())),
            temporal_pattern=data.get("temporal_pattern"),
            coexists_with=tuple(str(p).lower() for p in data.get("coexists_with", ())),
            requires_evidence=bool(data.get("requires_evidence", False)),
            sub_identity=bool(data.get("sub_identity", True)),
            protect_far_head=bool(data.get("protect_far_head", False)),
            sub_suppress=_ids("sub_suppress"),
        )

    @property
    def phrase_key(self) -> str:
        """The space-joined lowercased phrase other entries declare against."""
        return " ".join(self.phrase)

    def claim_atom(self) -> str | None:
        """The principal coordinate id this claim contributes, if any."""
        if self.claim == "head":
            return self.head
        if self.claim in ("modifier", "boundary"):
            return self.atom
        return None

    def payload_mods(self) -> tuple[str, ...]:
        """Modifier ids this claim asserts into the flat atom on attribution."""
        if self.claim == "head":
            return self.carriage
        if self.claim == "modifier":
            return self.also_asserts
        if self.claim == "relation":
            return self.projection
        if self.claim == "boundary":
            return self.carriage
        return ()

    def asserted_modifier_ids(self) -> frozenset[str]:
        """Every modifier id this claim can place in an atom."""
        ids = set(self.payload_mods())
        principal = self.claim_atom()
        if principal and principal.startswith("M_"):
            ids.add(principal)
        ids.update(m for m in self.operand_mods if m.startswith("M_"))
        return frozenset(ids)


@dataclass(frozen=True, slots=True)
class EvidenceContext:
    """Per-decomposition evidence satisfaction for one (accession, qname)."""

    accession: str
    qname: str
    satisfied: bool = False

    def allows(self, entry: LexiconEntry) -> bool:
        """True when this context satisfies the entry's evidence gate."""
        return self.satisfied


@dataclass(frozen=True, slots=True)
class LexiconMatch:
    """A contiguous matched segment within a sequence of tokens."""

    start: int
    end: int
    entry: LexiconEntry


class TokenLexicon:
    """Declarative vocabulary managing phrase matching and claim resolution."""

    def __init__(self, entries: tuple[LexiconEntry, ...]) -> None:
        """Initialize lexicon with entries indexed by phrase length."""
        self._entries = entries
        self._max_len = max((len(e.phrase) for e in entries), default=1)
        self._phrase_map: dict[tuple[str, ...], list[LexiconEntry]] = {}
        for entry in sorted(entries, key=lambda e: len(e.phrase), reverse=True):
            self._phrase_map.setdefault(entry.phrase, []).append(entry)
        self._file_order = {id(entry): i for i, entry in enumerate(entries)}
        self._modifier_kinds: dict[str, tuple[str, ...]] = {}

    @property
    def entries(self) -> tuple[LexiconEntry, ...]:
        """All configured lexical entries."""
        return self._entries

    @property
    def modifier_kinds(self) -> dict[str, tuple[str, ...]]:
        """Functional kinds per modifier id, attached by the taxonomy loader."""
        return self._modifier_kinds

    def attach_modifier_kinds(self, kinds: dict[str, tuple[str, ...]]) -> None:
        """Attach def kinds so attribution policies can read claim identity."""
        self._modifier_kinds = dict(kinds)

    @classmethod
    def load_json(cls, path: Path | str) -> TokenLexicon:
        """Load TokenLexicon from a JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        entries = tuple(LexiconEntry.from_dict(item) for item in data)
        return cls(entries)

    def candidates(
        self, tokens: tuple[str, ...], evidence: EvidenceContext | None = None
    ) -> list[LexiconMatch]:
        """Every claim whose phrase matches, overlaps preserved (RR1 pool).

        Scope conditions must be met by the following token.
        Evidence-gated claims fire only under a satisfied context.
        """
        lower_tokens = tuple(t.lower() for t in tokens)
        found: list[tuple[int, LexiconMatch]] = []
        n = len(tokens)
        for start in range(n):
            for length in range(1, min(self._max_len, n - start) + 1):
                alternatives = self._phrase_map.get(
                    lower_tokens[start : start + length]
                )
                if not alternatives:
                    continue
                for entry in alternatives:
                    if entry.requires_evidence and not (
                        evidence is not None and evidence.allows(entry)
                    ):
                        continue
                    if entry.scope_next:
                        following = (
                            lower_tokens[start + length] if start + length < n else None
                        )
                        if following not in entry.scope_next:
                            continue
                    found.append(
                        (
                            self._file_order[id(entry)],
                            LexiconMatch(start=start, end=start + length, entry=entry),
                        )
                    )
        found.sort(
            key=lambda pair: (pair[1].start, -(pair[1].end - pair[1].start), pair[0])
        )
        return [match for _, match in found]

    def select_cover(
        self,
        tokens: tuple[str, ...],
        candidates: list[LexiconMatch] | None = None,
        evidence: EvidenceContext | None = None,
    ) -> tuple[list[LexiconMatch], list[str]]:
        """Select the non-crossing cover: v1's greedy longest-at-position (RR1).

        Same-span ties go to the scope-conditioned claimant, then
        file order — the cover is the parity floor for v2 deltas.
        """
        pool = self.candidates(tokens, evidence) if candidates is None else candidates
        by_start: dict[int, list[LexiconMatch]] = {}
        for match in pool:
            by_start.setdefault(match.start, []).append(match)
        cover: list[LexiconMatch] = []
        residuals: list[str] = []
        i = 0
        n = len(tokens)
        while i < n:
            options = by_start.get(i)
            if not options:
                residuals.append(tokens[i])
                i += 1
                continue
            best_len = max(m.end for m in options) - i
            span = [m for m in options if m.end - m.start == best_len]
            scoped = [m for m in span if m.entry.scope_next]
            chosen = scoped[0] if scoped else span[0]
            cover.append(chosen)
            i = chosen.end
        return cover, residuals

    def scan_tokens(
        self, tokens: tuple[str, ...], evidence: EvidenceContext | None = None
    ) -> tuple[list[LexiconMatch], list[str]]:
        """The selected cover and the tokens it leaves uncovered."""
        return self.select_cover(tokens, evidence=evidence)
