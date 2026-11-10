"""Compositional concept decomposer extracting sub-atomic coordinates and frames."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import (
    ConceptDeclaration,
    qname_local,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, SemanticConceptFrame
from edgar_sec.engine.xbrl.taxonomy.item_types import (
    TextCoordinateRule,
    item_type_local,
)
from edgar_sec.engine.xbrl.normalize.lexicon import (
    EvidenceContext,
    LexiconMatch,
    TokenLexicon,
)
from edgar_sec.engine.xbrl.normalize.coordination import decompose_coordinated
from edgar_sec.engine.xbrl.normalize.flat import (
    _decompose_flat_tokens,
    _finish_resolution,
)
from edgar_sec.engine.xbrl.normalize.numbers import (
    collapse_number_phrases,
    number_indexicals,
)
from edgar_sec.engine.xbrl.normalize.temporal import TemporalInterval

_FRAME_STOCK_HEADS = frozenset({"H_COMMITMENT", "H_LIABILITY", "H_SHARE"})
_FRAME_ACTIVITY_MODIFIER = "M_INVESTING"
_FRAME_VALUATION_MODIFIER = "M_FAIR_VALUE"


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
    declaration: ConceptDeclaration | None = None,
    text_rule: TextCoordinateRule | None = None,
    evidence: EvidenceContext | None = None,
    percent_rule: TextCoordinateRule | None = None,
) -> tuple[Atom, tuple[str, ...], float, tuple[str, ...]]:
    """Decompose an XBRL concept QName into an Atom coordinate, residuals, and frame."""
    expression = decompose_concept_expression(
        concept_qname, lexicon, declaration, text_rule, evidence, percent_rule
    )
    return (
        expression.atom,
        expression.residuals,
        expression.direction,
        expression.indexicals,
    )


def _with_type_coordinate(
    atom: Atom,
    declaration: ConceptDeclaration | None,
    rule: TextCoordinateRule | None,
) -> Atom:
    """Assert a value-form coordinate on a headline atom from the declared type."""
    if declaration is None or rule is None:
        return atom
    if item_type_local(declaration.item_type) in rule.item_types:
        return Atom(atom.head, atom.modifiers | {rule.modifier_id})
    return atom


_STRUCTURAL_RESIDUAL_TOKENS = frozenset(
    {
        "abstract",
        "axis",
        "block",
        "description",
        "disclosure",
        "domain",
        "enumeration",
        "extensible",
        "information",
        "items",
        "level",
        "line",
        "lineitems",
        "measurement",
        "member",
        "period",
        "policy",
        "table",
        "text",
        "value",
    }
)

_NOISE_RESIDUAL_TOKENS = _STRUCTURAL_RESIDUAL_TOKENS | frozenset(
    {
        "a",
        "about",
        "after",
        "against",
        "an",
        "and",
        "arising",
        "as",
        "associated",
        "assumed",
        "at",
        "be",
        "before",
        "between",
        "by",
        "calculated",
        "during",
        "expected",
        "for",
        "from",
        "held",
        "in",
        "into",
        "is",
        "not",
        "of",
        "on",
        "or",
        "over",
        "per",
        "recognized",
        "related",
        "resulting",
        "schedule",
        "statement",
        "than",
        "the",
        "through",
        "to",
        "under",
        "upon",
        "used",
        "versus",
        "vs",
        "with",
        "within",
        "without",
    }
)


def is_noise_residual(token: str) -> bool:
    """True for stopword, structural, digit, or collapsed-number residuals."""
    lowered = token.lower()
    return (
        lowered in _NOISE_RESIDUAL_TOKENS
        or token.isdigit()
        or lowered in ("num", "ord")
    )


def residual_counts(residuals: tuple[str, ...]) -> tuple[int, int]:
    """(Intent-bearing, total) residual counts: a concept's residual mass."""
    intent = sum(1 for token in residuals if not is_noise_residual(token))
    return intent, len(residuals)


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


@lru_cache(maxsize=65536)
def decompose_concept_expression(
    concept_qname: str,
    lexicon: TokenLexicon,
    declaration: ConceptDeclaration | None = None,
    text_rule: TextCoordinateRule | None = None,
    evidence: EvidenceContext | None = None,
    percent_rule: TextCoordinateRule | None = None,
) -> ConceptExpression:
    """Preserve binary NET_OF operand atoms while deriving the query coordinate."""
    local_name = qname_local(concept_qname)
    raw_tokens = split_camel_case(local_name)
    tokens, number_values, ordinal_values = collapse_number_phrases(raw_tokens)
    candidates = lexicon.candidates(tokens, evidence)
    cover, cover_residuals = lexicon.select_cover(tokens, candidates)
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
            evidence,
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
            tokens[operator.end :], lexicon, (), right_values, right_ordinals, evidence
        )
        operator_atom = (
            operator.entry.projection[0] if operator.entry.projection else "V_NET"
        )
        return ConceptExpression(
            atom=_with_type_coordinate(
                _with_type_coordinate(
                    Atom(left.head, left.modifiers | {operator_atom}),
                    declaration,
                    text_rule,
                ),
                declaration,
                percent_rule,
            ),
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

    framed = _apply_grammatical_frame(
        tokens,
        lexicon,
        number_values,
        ordinal_values,
        evidence,
        declaration,
        text_rule,
        candidates,
    )
    if framed is not None:
        (
            atom,
            residuals,
            direction,
            indexicals,
            derived,
            relations,
            temporal,
            matches,
        ) = framed
    else:
        coordinated = decompose_coordinated(
            tokens,
            lexicon,
            number_values,
            ordinal_values,
            evidence,
            candidates,
            cover,
            cover_residuals,
        )
        if coordinated is not None:
            (
                raw_headline,
                operator,
                operand_atoms,
                weights,
                residuals,
                direction,
                indexicals,
                derived,
                relations,
                temporal,
                matches,
            ) = coordinated
            atom = _with_type_coordinate(
                _with_type_coordinate(raw_headline, declaration, text_rule),
                declaration,
                percent_rule,
            )
            return ConceptExpression(
                atom=atom,
                operator=operator,
                operands=(raw_headline, *operand_atoms) if operator else (atom,),
                weights=weights,
                residuals=residuals,
                direction=direction,
                indexicals=indexicals,
                derived_horizon=derived,
                relations=relations,
                temporal=temporal,
                matches=matches,
            )
        (
            atom,
            residuals,
            direction,
            indexicals,
            derived,
            relations,
            temporal,
            matches,
        ) = _decompose_flat_tokens(
            tokens,
            lexicon,
            number_indexicals(tokens, number_values, ordinal_values),
            number_values,
            ordinal_values,
            evidence,
            resolved=_finish_resolution(tokens, candidates, cover, cover_residuals),
        )
        atom = _apply_frame_head_precedence(
            tokens, lexicon, atom, declaration, text_rule
        )
    atom = _with_type_coordinate(atom, declaration, text_rule)
    atom = _with_type_coordinate(atom, declaration, percent_rule)
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


def _apply_grammatical_frame(
    tokens: tuple[str, ...],
    lexicon: TokenLexicon,
    number_values: dict[int, int],
    ordinal_values: dict[int, int],
    evidence: EvidenceContext | None,
    declaration: ConceptDeclaration | None,
    text_rule: TextCoordinateRule | None,
    candidates: list[LexiconMatch],
) -> (
    tuple[
        Atom,
        tuple[str, ...],
        float,
        tuple[str, ...],
        str | None,
        tuple[tuple[str, Atom], ...],
        TemporalInterval | None,
        tuple[LexiconMatch, ...],
    ]
    | None
):
    """Decompose under a leading act frame, or None when it refuses.

    Only act-declaring frames fire, and only on a flow remainder.
    """
    frame = lexicon.match_grammatical_frame(tokens)
    if frame is None or frame.act_modifier is None:
        return None
    prefix = len(frame.prefix_tokens)
    if any(
        match.start == 0 and match.entry.direction is not None for match in candidates
    ):
        return None
    lowered = tuple(t.lower() for t in tokens)
    if prefix >= len(tokens) or lowered[prefix] not in frame.strip_tokens:
        return None
    object_start = prefix
    while object_start < len(tokens) and lowered[object_start] in frame.strip_tokens:
        object_start += 1
    if object_start >= len(tokens):
        return None
    remainder = tokens[prefix:]
    remainder_candidates = lexicon.candidates(remainder, evidence)
    if any(match.entry.direction is not None for match in remainder_candidates):
        return None
    values = {i - prefix: v for i, v in number_values.items() if i >= prefix}
    ordinals = {i - prefix: v for i, v in ordinal_values.items() if i >= prefix}
    atom, residuals, _, indexicals, derived, relations, temporal, matches = (
        _decompose_flat_tokens(
            remainder,
            lexicon,
            number_indexicals(remainder, values, ordinals),
            values,
            ordinals,
            evidence,
            candidates=remainder_candidates,
        )
    )
    if atom.head in _FRAME_STOCK_HEADS:
        return None
    if (
        _FRAME_VALUATION_MODIFIER in atom.modifiers
        and _FRAME_ACTIVITY_MODIFIER not in atom.modifiers
    ):
        return None
    if declaration is not None and declaration.period_type == "instant":
        return None
    if (
        declaration is not None
        and text_rule is not None
        and item_type_local(declaration.item_type) in text_rule.item_types
    ):
        return None
    return (
        Atom(atom.head, atom.modifiers | {frame.act_modifier}),
        residuals,
        frame.direction,
        indexicals,
        derived,
        relations,
        temporal,
        tuple(LexiconMatch(m.start + prefix, m.end + prefix, m.entry) for m in matches),
    )


def _apply_frame_head_precedence(
    tokens: tuple[str, ...],
    lexicon: TokenLexicon,
    atom: Atom,
    declaration: ConceptDeclaration | None,
    text_rule: TextCoordinateRule | None,
) -> Atom:
    """Restore a frame-declared head the cover's pick outranked.

    Only the head moves; instant and text-typed declarations refuse.
    """
    frame = lexicon.match_grammatical_frame(tokens)
    if frame is None or frame.head is None or atom.head == frame.head:
        return atom
    if declaration is not None and declaration.period_type == "instant":
        return atom
    if (
        declaration is not None
        and text_rule is not None
        and item_type_local(declaration.item_type) in text_rule.item_types
    ):
        return atom
    return Atom(frame.head, atom.modifiers)


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
