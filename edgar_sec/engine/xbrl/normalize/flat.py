"""Flat-path decomposition: cover resolution, region split, and atom assembly."""

from __future__ import annotations

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.normalize.lexicon import (
    EvidenceContext,
    LexiconMatch,
    TokenLexicon,
)
from edgar_sec.engine.xbrl.normalize.temporal import (
    TemporalInterval,
    derive_horizon,
    extract_temporal,
)

_CLASS_RANK = {"PRIMARY": 3, "TAIL": 2, "INSTRUMENT": 1, "COMPOUND_QUALIFIER": 0}


def _uncovered_tokens(
    tokens: tuple[str, ...], spans: list[tuple[int, int]]
) -> list[str]:
    """The tokens no span covers, in stream order."""
    return [
        token
        for i, token in enumerate(tokens)
        if not any(start <= i < end for start, end in spans)
    ]


def _window_values(
    values: dict[int, int], start: int, end: int | None = None
) -> dict[int, int]:
    """The values inside [start, end), re-based to start; no end runs open."""
    return {
        i - start: v
        for i, v in values.items()
        if start <= i and (end is None or i < end)
    }


def _admit_coexisting(
    candidates: list[LexiconMatch], cover: list[LexiconMatch]
) -> list[LexiconMatch]:
    """Admit suppressed candidates a cover entry declares coexistence with.

    RR2: coexistence is a declared pair property, never global; an
    admitted claim may overlap only the named cover entries.
    """
    admitted: list[LexiconMatch] = []
    cover_ids = {id(m) for m in cover}
    cover_keys = [m.entry.phrase_key for m in cover]
    for cand in candidates:
        if id(cand) in cover_ids:
            continue
        cand_key = cand.entry.phrase_key
        cand_coexists = cand.entry.coexists_with
        partners = [
            m
            for m, key in zip(cover, cover_keys, strict=True)
            if m.start < cand.end
            and cand.start < m.end
            and (key in cand_coexists or cand_key in m.entry.coexists_with)
        ]
        if not partners:
            continue
        blockers = [
            m
            for m in cover
            if m.start < cand.end and cand.start < m.end and m not in partners
        ]
        if not blockers:
            admitted.append(cand)
    return admitted


def _resolve_matches(
    tokens: tuple[str, ...],
    lexicon: TokenLexicon,
    evidence: EvidenceContext | None = None,
    candidates: list[LexiconMatch] | None = None,
) -> tuple[list[LexiconMatch], list[str]]:
    """Resolve candidates to the attributing match list, in span order.

    The cover comes first at any shared start; admitted coexistence
    claims follow their cover partners.
    """
    if candidates is None:
        candidates = lexicon.candidates(tokens, evidence)
    cover, residuals = lexicon.select_cover(tokens, candidates)
    return _finish_resolution(tokens, candidates, cover, residuals)


def _finish_resolution(
    tokens: tuple[str, ...],
    candidates: list[LexiconMatch],
    cover: list[LexiconMatch],
    residuals: list[str],
) -> tuple[list[LexiconMatch], list[str]]:
    """Admit coexisting candidates over a computed cover; recompute residuals."""
    admitted = _admit_coexisting(candidates, cover)
    if not admitted:
        return cover, residuals
    remaining = _uncovered_tokens(tokens, [(m.start, m.end) for m in cover + admitted])
    resolved = sorted(cover + admitted, key=lambda m: (m.start, -(m.end - m.start)))
    return resolved, remaining


def _head_rank(match: LexiconMatch) -> int:
    return _CLASS_RANK.get(match.entry.claim_class or "", 0)


def _first_head_match(matches: list[LexiconMatch]) -> LexiconMatch | None:
    """The first positional head claim with a positive class rank, if any."""
    for m in matches:
        if m.entry.claim == "head" and m.entry.head and _head_rank(m) > 0:
            return m
    return None


def _pick_head(matches: list[LexiconMatch]) -> tuple[str, int | None]:
    """Pick the primary-region head: class priority, then v1's last position.

    COMPOUND_QUALIFIER claims never win a head (modifier-only class).
    """
    heads = [
        (idx, m)
        for idx, m in enumerate(matches)
        if m.entry.claim == "head" and m.entry.head and _head_rank(m) > 0
    ]
    if not heads:
        return "UNKNOWN", None
    best = max(_head_rank(m) for _, m in heads)
    top = [(idx, m) for idx, m in heads if _head_rank(m) == best]
    idx, match = top[-1]
    return match.entry.head or "UNKNOWN", idx


def _fallback_head(matches: list[LexiconMatch]) -> str:
    """Subordinate-region fallback head: v1's first positional head claim.

    The subordinate region is a specifier chain; its first head claim
    is the primary specifier, so position dominates class there.
    """
    match = _first_head_match(matches)
    return match.entry.head if match is not None and match.entry.head else "UNKNOWN"


def _tail_assembly(
    tokens: tuple[str, ...],
    matches: list[LexiconMatch],
    base_indexicals: tuple[str, ...],
    number_values: dict[int, int],
    ordinal_values: dict[int, int],
) -> tuple[float, tuple[str, ...], str | None, TemporalInterval | None]:
    """Direction, indexicals, horizon, and interval over one match list."""
    direction = 1.0
    for m in matches:
        if m.entry.direction is not None:
            direction = m.entry.direction
            break
    indexicals: list[str] = list(base_indexicals)
    for m in matches:
        if m.entry.claim == "indexical" and m.entry.indexical:
            indexicals.append(m.entry.indexical)
    temporal = extract_temporal(tokens, number_values, ordinal_values)
    return direction, tuple(indexicals), derive_horizon(temporal), temporal


def _split_regions(
    resolved: list[LexiconMatch],
) -> tuple[list[LexiconMatch], list[LexiconMatch], LexiconMatch | None]:
    """Split at the first boundary/relation claim.

    A protect_far_head boundary does not split when the far side's best head
    outranks the near side's; the far claim then wins under the global pick.
    """
    sub_idx: int | None = None
    for idx, match in enumerate(resolved):
        if match.entry.relation == "COORDINATION":
            continue  # coordination is expression-level; it never bounds a region
        if match.entry.claim in ("boundary", "relation"):
            sub_idx = idx
            break
    if sub_idx is None:
        return resolved, [], None
    boundary = resolved[sub_idx]
    if not boundary.entry.protect_far_head:
        return resolved[:sub_idx], resolved[sub_idx + 1 :], boundary
    near = resolved[:sub_idx]
    far = resolved[sub_idx + 1 :]
    near_heads = [m for m in near if m.entry.claim == "head" and _head_rank(m) > 0]
    far_heads = [m for m in far if m.entry.claim == "head" and _head_rank(m) > 0]
    if near_heads and far_heads:
        if max(_head_rank(m) for m in far_heads) > max(
            _head_rank(m) for m in near_heads
        ):
            return resolved, [], None
    return near, far, boundary


def _decompose_flat_tokens(
    tokens: tuple[str, ...],
    lexicon: TokenLexicon,
    num_indexicals: tuple[str, ...] = (),
    number_values: dict[int, int] | None = None,
    ordinal_values: dict[int, int] | None = None,
    evidence: EvidenceContext | None = None,
    candidates: list[LexiconMatch] | None = None,
    resolved: tuple[list[LexiconMatch], list[str]] | None = None,
) -> tuple[
    Atom,
    tuple[str, ...],
    float,
    tuple[str, ...],
    str | None,
    tuple[tuple[str, Atom], ...],
    TemporalInterval | None,
    tuple[LexiconMatch, ...],
]:
    if resolved is not None:
        matches, residuals = resolved
    else:
        matches, residuals = _resolve_matches(tokens, lexicon, evidence, candidates)
    direction, indexicals, derived, temporal = _tail_assembly(
        tokens, matches, num_indexicals, number_values or {}, ordinal_values or {}
    )

    primary_matches, subord_matches, boundary_match = _split_regions(matches)

    head, head_match_idx = _pick_head(primary_matches)
    if head_match_idx is None:
        head = _fallback_head(subord_matches)

    sub_identity = boundary_match.entry.sub_identity if boundary_match else True
    sub_suppress = (
        frozenset(boundary_match.entry.sub_suppress) if boundary_match else frozenset()
    )
    kinds = lexicon.modifier_kinds

    def _subordinate_suppressed(mod: str) -> bool:
        return mod in sub_suppress or (
            not sub_identity and "IDENTITY" in kinds.get(mod, ())
        )

    mods: set[str] = set()
    for idx, m in enumerate(primary_matches):
        principal = m.entry.claim_atom()
        if idx != head_match_idx and principal and m.entry.claim != "head":
            mods.add(principal)
        mods.update(m.entry.payload_mods())

    for m in subord_matches:
        principal = m.entry.claim_atom()
        if principal and m.entry.claim != "head":
            if not _subordinate_suppressed(principal):
                mods.add(principal)
        for mod in m.entry.payload_mods():
            if _subordinate_suppressed(mod):
                continue
            mods.add(mod)

    if boundary_match is not None:
        principal = boundary_match.entry.claim_atom()
        if principal and boundary_match.entry.claim != "head":
            mods.add(principal)
        mods.update(boundary_match.entry.payload_mods())

    relations: list[tuple[str, Atom]] = []
    for m in matches:
        if m.entry.claim == "relation" and m.entry.relation in (
            "EXCLUDING",
            "INCLUDING",
        ):
            relations.append(
                (m.entry.relation, Atom("H_UNKNOWN", frozenset(m.entry.operand_mods)))
            )

    atom = Atom(head=head, modifiers=frozenset(mods))
    return (
        atom,
        tuple(residuals),
        direction,
        indexicals,
        derived,
        tuple(relations),
        temporal,
        tuple(matches),
    )
