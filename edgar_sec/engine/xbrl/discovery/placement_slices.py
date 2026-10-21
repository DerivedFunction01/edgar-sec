"""Statement placement slices derived from presentation-arc roots."""

from __future__ import annotations

import json

import pyarrow as pa

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept_expression
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths


def tokenize_fact_concept(concept_qname: str) -> list[str]:
    """Tokenize a concept QName into normalized lowercased word stems."""
    local = concept_qname.split(":")[-1]
    tokens: list[str] = []
    current: list[str] = []

    for i, ch in enumerate(local):
        if not ch.isalnum():
            if current:
                tokens.append("".join(current).lower())
                current = []
            continue
        if (
            ch.isupper()
            and current
            and (
                i + 1 < len(local)
                and local[i + 1].islower()
                or not current[-1].isupper()
            )
        ):
            tokens.append("".join(current).lower())
            current = [ch]
        else:
            current.append(ch)

    if current:
        tokens.append("".join(current).lower())
    return [t for t in tokens if t]


def _statement_root_patterns() -> tuple[dict, ...]:
    """Load statement-root coordinate patterns from the taxonomy data."""
    path = resolve_xbrl_paths().default_statement_roots_path
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def _root_slice(
    qname: str, lexicon: TokenLexicon, patterns: tuple[dict, ...]
) -> str | None:
    """Classify one presentation root by the declared coordinate patterns."""
    namespace = qname.split(":", 1)[0] if ":" in qname else ""
    tokens = set(tokenize_fact_concept(qname))
    head = decompose_concept_expression(qname, lexicon).atom.head
    for pattern in patterns:
        if pattern.get("namespace") and pattern["namespace"] != namespace:
            continue
        if pattern.get("head") and pattern["head"] != head:
            continue
        if not set(pattern.get("tokens_all", ())) <= tokens:
            continue
        return str(pattern["slice"])
    return None


def placement_slices(
    arcs: pa.Table | None, lexicon: TokenLexicon
) -> dict[str, set[str]]:
    """Propagate statement slices from derived presentation roots down arcs."""
    if arcs is None or "parent_qname" not in arcs.column_names:
        return {}
    edges = list(
        zip(
            arcs.column("parent_qname").to_pylist(),
            arcs.column("child_qname").to_pylist(),
        )
    )
    children = {child for _, child in edges}
    patterns = _statement_root_patterns()
    slices: dict[str, set[str]] = {}
    seeded: set[str] = set()
    seen_roots: set[str] = set()
    for parent, _ in edges:
        if parent in children or parent in seen_roots:
            continue
        seen_roots.add(parent)
        slice_ = _root_slice(parent, lexicon, patterns)
        if slice_ is not None:
            slices[parent] = {slice_}
            seeded.add(parent)
    changed = True
    while changed:
        changed = False
        for parent, child in edges:
            source = slices.get(parent)
            if not source:
                continue
            target = slices.setdefault(child, set())
            if not source <= target:
                target |= source
                changed = True
    return {q: s for q, s in slices.items() if q not in seeded}
