"""Statement placement slices derived from presentation-arc roots."""

from __future__ import annotations

import json

import pyarrow as pa

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept_expression
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.schema.models import qname_local, split_concept_qname


def tokenize_fact_concept(concept_qname: str) -> list[str]:
    """Tokenize a concept QName into normalized lowercased word stems."""
    local = qname_local(concept_qname)
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
    namespace = split_concept_qname(qname)[0]
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


def _partition_slices(
    edges: list[tuple[str, str]],
    lexicon: TokenLexicon,
    patterns: tuple[dict, ...],
) -> dict[str, set[str]]:
    """Slices for one role partition: seed its roots, propagate down."""
    children = {child for _, child in edges}
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


def placement_slices(
    arcs: pa.Table | None, lexicon: TokenLexicon
) -> dict[str, set[str]]:
    """Propagate statement slices from derived presentation roots down arcs.
    Per role when role_uri is present: roles are separate trees, so slices
    never cross roles through shared concepts."""
    if arcs is None or "parent_qname" not in arcs.column_names:
        return {}
    parents = arcs.column("parent_qname").to_pylist()
    children = arcs.column("child_qname").to_pylist()
    if "role_uri" in arcs.column_names:
        roles = arcs.column("role_uri").to_pylist()
    else:
        roles = [None] * len(parents)
    partitions: dict[str, list[tuple[str, str]]] = {}
    for role, parent, child in zip(roles, parents, children):
        partitions.setdefault(role or "", []).append((parent, child))
    patterns = _statement_root_patterns()
    merged: dict[str, set[str]] = {}
    for edges in partitions.values():
        for qname, slices in _partition_slices(edges, lexicon, patterns).items():
            merged.setdefault(qname, set()).update(slices)
    return merged
