"""Declarative token lexicon: typed phrase claims and phrase scanning."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import product
import json
from pathlib import Path
from typing import Any

from edgar_sec.engine.xbrl.taxonomy.records import GrammaticalFrame

CLAIM_KINDS = ("head", "modifier", "boundary", "relation", "indexical")
HEAD_CLAIM_CLASSES = ("PRIMARY", "INSTRUMENT", "TAIL", "COMPOUND_QUALIFIER")
RELATION_KINDS = ("NET_OF", "EXCLUDING", "INCLUDING", "COORDINATION")


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


_LIST_FIELDS = (
    "carriage",
    "also_asserts",
    "operand_mods",
    "projection",
    "scope_next",
    "coexists_with",
    "sub_suppress",
)
_LOWERED_LIST_FIELDS = ("scope_next", "coexists_with")
_BOOL_FIELDS = ("requires_evidence", "sub_identity", "protect_far_head")


def _apply_override(
    entry: LexiconEntry, combo: tuple[str, ...], override: dict[str, Any]
) -> LexiconEntry:
    """A generated entry carrying its declared per-form override.

    Field conversion mirrors LexiconEntry.from_dict exactly, and the
    merged entry passes the same claim validations from_dict runs.
    """
    fields: dict[str, Any] = {"phrase": combo}
    for key, raw in override.items():
        if key == "phrase":
            fields[key] = (
                tuple(p.lower() for p in raw.split())
                if isinstance(raw, str)
                else tuple(str(p).lower() for p in raw)
            )
        elif key in _LOWERED_LIST_FIELDS:
            fields[key] = tuple(str(t).lower() for t in raw)
        elif key in _LIST_FIELDS:
            fields[key] = (
                tuple(str(m) for m in raw) if isinstance(raw, (list, tuple)) else ()
            )
        elif key == "claim":
            fields[key] = str(raw).lower()
        elif key == "direction":
            fields[key] = float(raw)
        elif key in _BOOL_FIELDS:
            fields[key] = bool(raw)
        else:
            fields[key] = raw
    generated = replace(entry, **fields)
    phrase = generated.phrase
    if generated.claim not in CLAIM_KINDS:
        raise ValueError(
            f"lexicon entry {phrase} has unknown claim {generated.claim!r}"
        )
    if generated.claim == "head":
        if not generated.head:
            raise ValueError(f"head claim {phrase} names no head")
        if generated.claim_class not in HEAD_CLAIM_CLASSES:
            raise ValueError(
                f"head claim {phrase} must declare a claim class"
                f" (one of {HEAD_CLAIM_CLASSES})"
            )
    if generated.claim == "relation" and generated.relation not in RELATION_KINDS:
        raise ValueError(
            f"relation claim {phrase} has unknown kind {generated.relation!r}"
        )
    return generated


@dataclass(frozen=True, slots=True)
class InflectionTable:
    """Declared surface forms per canonical token, with split pairs refused."""

    forms: dict[str, tuple[str, ...]]
    overrides: dict[tuple[str, ...], dict[str, Any]]
    split: tuple[tuple[str, str], ...]
    verbatim: tuple[tuple[str, ...], ...] = ()
    _index: dict[str, tuple[str, tuple[str, ...]]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self._index:
            index: dict[str, tuple[str, tuple[str, ...]]] = {}
            for canonical, surfaces in self.forms.items():
                for surface in surfaces:
                    index.setdefault(surface, (canonical, surfaces))
            object.__setattr__(self, "_index", index)

    def family(self, token: str) -> tuple[str, ...] | None:
        """The declared surface forms of the family containing token, if any."""
        hit = self._index.get(token)
        return hit[1] if hit is not None else None

    def canonical(self, token: str) -> str:
        """The canonical form of token under this table (itself if undeclared)."""
        hit = self._index.get(token)
        return hit[0] if hit is not None else token


def load_inflection_table(path: Path | str) -> InflectionTable:
    """Load and validate an inflection table from JSON."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    forms: dict[str, tuple[str, ...]] = {}
    seen: dict[str, str] = {}
    for canonical, surfaces in data.get("forms", {}).items():
        canon = str(canonical).lower()
        forms_tuple = tuple(str(s).lower() for s in surfaces)
        if canon not in forms_tuple:
            raise ValueError(f"inflection family {canon} omits its canonical form")
        for surface in forms_tuple:
            if surface in seen:
                raise ValueError(f"token {surface} declared in two inflection families")
            seen[surface] = canon
        forms[canon] = forms_tuple
    split = tuple(tuple(str(t).lower() for t in pair) for pair in data.get("split", ()))
    for pair in split:
        for token in pair:
            if token in seen:
                raise ValueError(f"split token {token} is also a declared form")
    overrides = {
        tuple(str(t).lower() for t in key.split()): dict(fields)
        for key, fields in data.get("overrides", {}).items()
    }
    verbatim = tuple(
        tuple(str(t).lower() for t in phrase) for phrase in data.get("verbatim", ())
    )
    return InflectionTable(
        forms=forms, overrides=overrides, split=split, verbatim=verbatim
    )


def expand_lexicon_entries(
    entries: tuple[LexiconEntry, ...], table: InflectionTable
) -> tuple[LexiconEntry, ...]:
    """Expand authored entries over the declared surface forms.

    A generated phrase meeting a differently-payloaded authored entry is
    a loader error; verbatim phrases load ungenerated, exactly as authored.
    """
    authored: dict[tuple[str, ...], set[LexiconEntry]] = {}
    for entry in entries:
        authored.setdefault(entry.phrase, set()).add(entry)
    out: list[LexiconEntry] = []
    emitted: set[LexiconEntry] = set()
    by_surface: dict[tuple[str, ...], dict[tuple[str, ...], set[LexiconEntry]]] = {}
    used_overrides: set[tuple[str, ...]] = set()
    for entry in entries:
        if entry.phrase in table.verbatim:
            if entry not in emitted:
                emitted.add(entry)
                out.append(entry)
            continue
        source = tuple(table.canonical(t) for t in entry.phrase)
        variants = [table.family(t) or (t,) for t in entry.phrase]
        for combo in product(*variants):
            override = table.overrides.get(combo)
            if override is None:
                generated = replace(entry, phrase=combo)
            else:
                used_overrides.add(combo)
                generated = _apply_override(entry, combo, override)
            payloads = by_surface.setdefault(combo, {}).setdefault(source, set())
            payloads.add(generated)
            if generated in emitted:
                continue
            if combo in authored and generated not in authored[combo]:
                raise ValueError(
                    f"inflection expansion generates {combo} against its authored entry"
                )
            emitted.add(generated)
            out.append(generated)
    for combo, sources in by_surface.items():
        payload_sets = list(sources.values())
        if len(sources) > 1 and any(s != payload_sets[0] for s in payload_sets[1:]):
            raise ValueError(
                f"inflection expansion of several phrases generates {combo}"
            )
    stale = set(table.overrides) - used_overrides
    if stale:
        raise ValueError(f"inflection overrides never applied: {sorted(stale)}")
    return tuple(out)


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
        self._grammatical_frames: tuple[GrammaticalFrame, ...] = ()

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

    @property
    def grammatical_frames(self) -> tuple[GrammaticalFrame, ...]:
        """Grammatical frames attached by the taxonomy loader."""
        return self._grammatical_frames

    def attach_grammatical_frames(self, frames: tuple[GrammaticalFrame, ...]) -> None:
        """Attach the declared frames so decomposition can consult them."""
        self._grammatical_frames = tuple(frames)

    def match_grammatical_frame(
        self, tokens: tuple[str, ...]
    ) -> GrammaticalFrame | None:
        """The first declared frame whose prefix matches the leading tokens."""
        lowered = tuple(t.lower() for t in tokens)
        for frame in self._grammatical_frames:
            k = len(frame.prefix_tokens)
            if len(lowered) >= k and lowered[:k] == frame.prefix_tokens:
                return frame
        return None

    @classmethod
    def load_json(
        cls, path: Path | str, inflections_path: Path | str | None = None
    ) -> TokenLexicon:
        """Load TokenLexicon from JSON, expanding declared inflections.

        The table defaults to an `inflections.json` beside the lexicon file.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        entries = tuple(LexiconEntry.from_dict(item) for item in data)
        table_path = (
            Path(inflections_path)
            if inflections_path is not None
            else Path(path).parent / "inflections.json"
        )
        if table_path.is_file():
            entries = expand_lexicon_entries(entries, load_inflection_table(table_path))
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
