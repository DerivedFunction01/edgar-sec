"""Compositional concept decomposer extracting sub-atomic coordinates and frames."""

from __future__ import annotations

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, SemanticConceptFrame
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon


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
    local_name = concept_qname.split(":")[-1] if ":" in concept_qname else concept_qname
    tokens = split_camel_case(local_name)
    matches, residuals = lexicon.scan_tokens(tokens)

    sub_idx: int | None = None
    for idx, match in enumerate(matches):
        if match.entry.role == "SUBORDINATOR":
            sub_idx = idx
            break

    if sub_idx is not None:
        primary_matches = matches[:sub_idx]
        subord_matches = matches[sub_idx + 1 :]
    else:
        primary_matches = matches
        subord_matches = []

    head = "UNKNOWN"
    head_match_idx: int | None = None
    for idx in range(len(primary_matches) - 1, -1, -1):
        m = primary_matches[idx]
        if m.entry.role == "HEAD" and m.entry.atom:
            head = m.entry.atom
            head_match_idx = idx
            break

    if head_match_idx is None:
        for m in subord_matches:
            if m.entry.role == "HEAD" and m.entry.atom:
                head = m.entry.atom
                break

    mods: set[str] = set()
    for idx, m in enumerate(primary_matches):
        if idx != head_match_idx and m.entry.atom:
            mods.add(m.entry.atom)
        if m.entry.mods:
            mods.update(m.entry.mods)

    for m in subord_matches:
        if m.entry.atom:
            mods.add(m.entry.atom)
        if m.entry.mods:
            mods.update(m.entry.mods)

    direction = 1.0
    for m in matches:
        if m.entry.direction is not None:
            direction = m.entry.direction
            break

    indexicals: list[str] = []
    for m in matches:
        if m.entry.role == "INDEXICAL" and m.entry.indexical:
            indexicals.append(m.entry.indexical)

    atom = Atom(head=head, modifiers=frozenset(mods))
    return atom, tuple(residuals), direction, tuple(indexicals)


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
        from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths

        x_paths = resolve_xbrl_paths()
        lexicon = TokenLexicon.load_json(x_paths.default_token_lexicon_path)
    else:
        lexicon = taxonomy.token_lexicon

    atom, residuals, direction, _ = decompose_concept(concept_qname, lexicon)

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
        elif mod_id == "M_FAIR_VALUE":
            valuation = "FAIR_VALUE"
        elif mod_id == "M_UNREALIZED":
            realization = "UNREALIZED_M2M"

    return SemanticConceptFrame(
        qname=concept_qname,
        prime_head=atom.head,
        modifiers=tuple(sorted(atom.modifiers)),
        atom=atom,
        residual_tokens=residuals,
        recognition_book=book,
        flow_stock=flow_stock,
        timing_horizon=horizon,
        valuation_basis=valuation,
        realization_state=realization,
        expected_weight=int(direction),
    )
