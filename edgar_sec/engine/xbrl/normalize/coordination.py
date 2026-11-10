"""Coordination operator: per-conjunct atoms for unspanned `and` coordinations."""

from __future__ import annotations

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.normalize.flat import (
    _decompose_flat_tokens,
    _finish_resolution,
    _head_rank,
    _pick_head,
    _split_regions,
)
from edgar_sec.engine.xbrl.normalize.lexicon import (
    EvidenceContext,
    LexiconMatch,
    TokenLexicon,
)
from edgar_sec.engine.xbrl.normalize.numbers import number_indexicals
from edgar_sec.engine.xbrl.normalize.temporal import (
    TemporalInterval,
    derive_horizon,
    extract_temporal,
)

CoordinatedParts = tuple[
    Atom,
    str | None,
    tuple[Atom, ...],
    tuple[float, ...],
    tuple[str, ...],
    float,
    tuple[str, ...],
    str | None,
    tuple[tuple[str, Atom], ...],
    TemporalInterval | None,
    tuple[LexiconMatch, ...],
]


def decompose_coordinated(
    tokens: tuple[str, ...],
    lexicon: TokenLexicon,
    number_values: dict[int, int],
    ordinal_values: dict[int, int],
    evidence: EvidenceContext | None,
    candidates: list[LexiconMatch],
    cover: list[LexiconMatch],
    cover_residuals: list[str],
) -> CoordinatedParts | None:
    """Assemble per-conjunct atoms, or None when coordination does not engage."""
    frame = lexicon.match_grammatical_frame(tokens)
    if frame is not None and frame.head is not None:
        return None
    resolved, _ = _finish_resolution(tokens, candidates, cover, cover_residuals)
    operators = [m for m in resolved if m.entry.relation == "COORDINATION"]
    if not operators:
        return None
    if any(
        "and" in m.entry.phrase and m.entry.relation != "COORDINATION" for m in resolved
    ):
        return None
    spans = [(m.start, m.end) for m in operators]
    others = [m for m in resolved if m.entry.relation != "COORDINATION"]
    if any(m.start < end and start < m.end for m in others for start, end in spans):
        return None
    starts = [0] + [end for _, end in spans]
    ends = [start for start, _ in spans] + [len(tokens)]
    segments: list[tuple[Atom, tuple[str, ...], tuple[tuple[str, Atom], ...]]] = []
    for seg_start, seg_end in zip(starts, ends, strict=True):
        seg_tokens = tokens[seg_start:seg_end]
        seg_matches = [
            LexiconMatch(m.start - seg_start, m.end - seg_start, m.entry)
            for m in others
            if seg_start <= m.start and m.end <= seg_end
        ]
        covered = [(m.start, m.end) for m in seg_matches]
        seg_residuals = [
            token
            for i, token in enumerate(seg_tokens)
            if not any(s <= i < e for s, e in covered)
        ]
        values = {
            i - seg_start: v
            for i, v in number_values.items()
            if seg_start <= i < seg_end
        }
        ordinals = {
            i - seg_start: v
            for i, v in ordinal_values.items()
            if seg_start <= i < seg_end
        }
        atom, residuals, _, _, _, relations, _, _ = _decompose_flat_tokens(
            seg_tokens,
            lexicon,
            number_indexicals(seg_tokens, values, ordinals),
            values,
            ordinals,
            evidence,
            resolved=(seg_matches, seg_residuals),
        )
        segments.append((atom, residuals, relations))
    if sum(1 for atom, _, _ in segments if atom.head != "H_UNKNOWN") < 2:
        return None
    primary, subordinate, _ = _split_regions(resolved)
    head, head_idx = _pick_head(primary)
    if head_idx is not None:
        winner = primary[head_idx]
    else:
        winner = next(
            (
                m
                for m in subordinate
                if m.entry.claim == "head" and m.entry.head and _head_rank(m) > 0
            ),
            None,
        )
        if winner is None:
            return None
        head = winner.entry.head or head
    headline_idx = next(
        (
            i
            for i, (s, e) in enumerate(zip(starts, ends, strict=True))
            if s <= winner.start and winner.end <= e
        ),
        None,
    )
    if headline_idx is None or segments[headline_idx][0].head != head:
        return None
    mods = set(segments[headline_idx][0].modifiers)
    operands: list[Atom] = []
    relations: list[tuple[str, Atom]] = []
    for i, (atom, _, seg_relations) in enumerate(segments):
        relations.extend(seg_relations)
        if i == headline_idx:
            continue
        if atom.head == "H_UNKNOWN" or atom.head == head:
            mods.update(atom.modifiers)
        else:
            operands.append(atom)
            relations.append(("COORDINATION", atom))
    headline = Atom(head, frozenset(mods))
    direction = 1.0
    for m in resolved:
        if m.entry.direction is not None:
            direction = m.entry.direction
            break
    indexicals = list(number_indexicals(tokens, number_values, ordinal_values))
    for m in resolved:
        if m.entry.claim == "indexical" and m.entry.indexical:
            indexicals.append(m.entry.indexical)
    temporal = extract_temporal(tokens, number_values, ordinal_values)
    residuals = tuple(r for _, seg_residuals, _ in segments for r in seg_residuals)
    parts = (
        residuals,
        direction,
        tuple(indexicals),
        derive_horizon(temporal),
        tuple(relations),
        temporal,
        tuple(resolved),
    )
    if operands:
        return (
            headline,
            "COORDINATION",
            tuple(operands),
            (1.0,) * (1 + len(operands)),
            *parts,
        )
    return (headline, None, (), (1.0,), *parts)
