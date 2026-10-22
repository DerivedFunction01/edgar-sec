"""Compositional concept decomposer extracting sub-atomic coordinates and frames."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, SemanticConceptFrame
from edgar_sec.engine.xbrl.normalize.lexicon import LexiconMatch, TokenLexicon
from edgar_sec.engine.xbrl.normalize.numbers import (
    collapse_number_phrases,
    number_indexicals,
)
from edgar_sec.engine.xbrl.normalize.temporal import (
    TemporalInterval,
    derive_horizon,
    extract_temporal,
)

_CLASS_RANK = {"PRIMARY": 3, "TAIL": 2, "INSTRUMENT": 1, "COMPOUND_QUALIFIER": 0}


def split_camel_case(name: str) -> tuple[str, ...]:
    """Split CamelCase identifier into individual word tokens."""
    cleaned = name.replace("_", " ")
    tokens: list[str] = []
    current: list[str] = []
    for i, ch in enumerate(cleaned):
        if ch.isupper() and current:
            prev = cleaned[i - 1]
            next_ch = cleaned[i + 1] if i + 1 < len(cleaned) else ""
            if prev.islower() or (next_ch and next_ch.islower()):
                tokens.append("".join(current))
                current = []
        elif ch.isdigit() and current and not cleaned[i - 1].isdigit():
            tokens.append("".join(current))
            current = []
        elif ch.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(ch)
    if current:
        tokens.append("".join(current))
    return tuple(t for t in tokens if t)


def decompose_concept(
    concept_qname: str,
    lexicon: TokenLexicon,
) -> tuple[Atom, tuple[str, ...], float, tuple[str, ...]]:
    """Decompose an XBRL concept QName into an Atom coordinate, residuals, and frame."""
    expression = decompose_concept_expression(concept_qname, lexicon)
    return (
        expression.atom,
        expression.residuals,
        expression.direction,
        expression.indexicals,
    )


@dataclass(frozen=True, slots=True)
class ConceptExpression:
    atom: Atom
    operator: str | None
    operands: tuple[Atom, ...]
    weights: tuple[float, ...]
    residuals: tuple[str, ...]
    direction: float = 1.0
    indexicals: tuple[str, ...] = ()
    derived_horizon: str | None = None
    relations: tuple[tuple[str, Atom], ...] = ()
    temporal: TemporalInterval | None = None
    matches: tuple[LexiconMatch, ...] = ()


def decompose_concept_expression(
    concept_qname: str,
    lexicon: TokenLexicon,
) -> ConceptExpression:
    """Preserve binary NET_OF operand atoms while deriving the query coordinate."""
    local_name = concept_qname.split(":")[-1] if ":" in concept_qname else concept_qname
    raw_tokens = split_camel_case(local_name)
    tokens, number_values, ordinal_values = collapse_number_phrases(raw_tokens)
    cover, _ = lexicon.select_cover(tokens)
    operators = [
        match
        for match in cover
        if match.entry.claim == "relation" and match.entry.relation == "NET_OF"
    ]
    if len(operators) > 1:
        return ConceptExpression(
            atom=Atom("H_UNKNOWN"),
            operator=None,
            operands=(),
            weights=(),
            residuals=raw_tokens,
        )
    if operators:
        operator = operators[0]
        left_tokens = tokens[: operator.start]
        left_values = {i: v for i, v in number_values.items() if i < operator.start}
        left_ordinals = {i: v for i, v in ordinal_values.items() if i < operator.start}
        (
            left,
            left_residuals,
            direction,
            indexicals,
            left_derived,
            left_relations,
            left_temporal,
            left_matches,
        ) = _decompose_flat_tokens(
            left_tokens,
            lexicon,
            number_indexicals(left_tokens, left_values, left_ordinals),
            left_values,
            left_ordinals,
        )
        right_values = {
            i - operator.end: v for i, v in number_values.items() if i >= operator.end
        }
        right_ordinals = {
            i - operator.end: v for i, v in ordinal_values.items() if i >= operator.end
        }
        (
            right,
            right_residuals,
            _,
            _,
            right_derived,
            right_relations,
            right_temporal,
            right_matches,
        ) = _decompose_flat_tokens(
            tokens[operator.end :], lexicon, (), right_values, right_ordinals
        )
        operator_atom = (
            operator.entry.projection[0] if operator.entry.projection else "V_NET"
        )
        return ConceptExpression(
            atom=Atom(left.head, left.modifiers | {operator_atom}),
            operator="NET_OF",
            operands=(left, right),
            weights=(1.0, -1.0),
            residuals=left_residuals + right_residuals,
            direction=direction,
            indexicals=indexicals,
            derived_horizon=(
                left_derived if left_derived is not None else right_derived
            ),
            relations=left_relations + (("NET_OF", right),) + right_relations,
            temporal=left_temporal if left_temporal is not None else right_temporal,
            matches=left_matches
            + (operator,)
            + tuple(
                LexiconMatch(m.start + operator.end, m.end + operator.end, m.entry)
                for m in right_matches
            ),
        )

    atom, residuals, direction, indexicals, derived, relations, temporal, matches = (
        _decompose_flat_tokens(
            tokens,
            lexicon,
            number_indexicals(tokens, number_values, ordinal_values),
            number_values,
            ordinal_values,
        )
    )
    return ConceptExpression(
        atom=atom,
        operator=None,
        operands=(atom,),
        weights=(1.0,),
        residuals=residuals,
        direction=direction,
        indexicals=indexicals,
        derived_horizon=derived,
        relations=relations,
        temporal=temporal,
        matches=matches,
    )


def _admit_coexisting(
    candidates: list[LexiconMatch], cover: list[LexiconMatch]
) -> list[LexiconMatch]:
    """Admit suppressed candidates a cover entry declares coexistence with.

    RR2: coexistence is a declared pair property, never global; an
    admitted claim may overlap only the named cover entries.
    """
    admitted: list[LexiconMatch] = []
    cover_ids = {id(m) for m in cover}
    for cand in candidates:
        if id(cand) in cover_ids:
            continue
        partners = [
            m
            for m in cover
            if m.start < cand.end
            and cand.start < m.end
            and (
                m.entry.phrase_key in cand.entry.coexists_with
                or cand.entry.phrase_key in m.entry.coexists_with
            )
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
    tokens: tuple[str, ...], lexicon: TokenLexicon
) -> tuple[list[LexiconMatch], list[str]]:
    """Resolve candidates to the attributing match list, in span order.

    The cover comes first at any shared start; admitted coexistence
    claims follow their cover partners.
    """
    candidates = lexicon.candidates(tokens)
    cover, residuals = lexicon.select_cover(tokens, candidates)
    admitted = _admit_coexisting(candidates, cover)
    if not admitted:
        return cover, residuals
    spans = [(m.start, m.end) for m in cover + admitted]
    remaining = [
        token
        for i, token in enumerate(tokens)
        if not any(start <= i < end for start, end in spans)
    ]
    resolved = sorted(cover + admitted, key=lambda m: (m.start, -(m.end - m.start)))
    return resolved, remaining


def _head_rank(match: LexiconMatch) -> int:
    return _CLASS_RANK.get(match.entry.claim_class or "", 0)


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
    for m in matches:
        if m.entry.claim == "head" and m.entry.head and _head_rank(m) > 0:
            return m.entry.head
    return "UNKNOWN"


def _split_regions(
    resolved: list[LexiconMatch],
) -> tuple[list[LexiconMatch], list[LexiconMatch], LexiconMatch | None]:
    """Split at the first boundary/relation claim.

    A protect_far_head boundary does not split when the far side's best head
    outranks the near side's; the far claim then wins under the global pick.
    """
    sub_idx: int | None = None
    for idx, match in enumerate(resolved):
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
    matches, residuals = _resolve_matches(tokens, lexicon)
    temporal = extract_temporal(tokens, number_values or {}, ordinal_values or {})
    derived = derive_horizon(temporal)

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

    direction = 1.0
    for m in matches:
        if m.entry.direction is not None:
            direction = m.entry.direction
            break

    indexicals: list[str] = list(num_indexicals)
    for m in matches:
        if m.entry.claim == "indexical" and m.entry.indexical:
            indexicals.append(m.entry.indexical)

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
        tuple(indexicals),
        derived,
        tuple(relations),
        temporal,
        tuple(matches),
    )


def infer_semantic_frame(
    concept_qname: str,
    taxonomy: DomainTaxonomy,
    *,
    unit: str | None = None,
    balance: str | None = None,
    role_uri: str | None = None,
) -> SemanticConceptFrame:
    """Decompose an XBRL concept into a structured semantic concept frame."""
    if taxonomy.token_lexicon is None:
        from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy

        loaded = load_domain_taxonomy().token_lexicon
        assert loaded is not None
        lexicon = loaded
    else:
        lexicon = taxonomy.token_lexicon

    expression = decompose_concept_expression(concept_qname, lexicon)
    atom = expression.atom

    head_def = taxonomy.prime_head(atom.head)
    book = head_def.recognition_book if head_def else "UNKNOWN"
    flow_stock = head_def.flow_stock if head_def else "UNKNOWN"
    horizon = head_def.timing_horizon if head_def else "UNKNOWN"

    valuation = "HISTORICAL_AMORTIZED_COST"
    realization = "REALIZED_P_L"

    for mod_id in atom.modifiers:
        mod_def = taxonomy.modifier(mod_id)
        if mod_def is not None:
            if mod_def.valuation_basis:
                valuation = mod_def.valuation_basis
            if mod_def.realization_state:
                realization = mod_def.realization_state

    return SemanticConceptFrame(
        qname=concept_qname,
        prime_head=atom.head,
        modifiers=tuple(sorted(atom.modifiers)),
        atom=atom,
        residual_tokens=expression.residuals,
        recognition_book=book,
        flow_stock=flow_stock,
        timing_horizon=horizon,
        valuation_basis=valuation,
        realization_state=realization,
        expected_weight=int(expression.direction),
        indexicals=expression.indexicals,
        temporal=expression.temporal,
    )
