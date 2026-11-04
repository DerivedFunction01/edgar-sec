"""Presentation catalog: one entry per presentation role in a filing.

Titles and categories are derived mechanically from the role URI and
the declared statement slices; no per-role or per-company tables.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from edgar_sec.engine.xbrl.discovery.placement_slices import tokenize_fact_concept
from edgar_sec.engine.xbrl.normalize.decomposer import split_camel_case
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.schema.models import (
    PresentationArc,
    qname_local,
    split_concept_qname,
)

if TYPE_CHECKING:
    import pandas as pd

    from edgar_sec.apps.client.kernel import FilingKernel

STATEMENT = "statement"
DOCUMENT = "document"
NOTE = "note"
DISCLOSURE = "disclosure"

_CATEGORY_SEGMENTS = frozenset({"statement", "disclosure", "document"})
_DETAIL_SUFFIXES = frozenset({"detail", "details", "disclosure"})
# Stop words admitted only as segmentation pieces; each was validated
# on the seed-corpus title sweep (Step 5 addendum run-log).
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "per",
        "the",
        "to",
        "with",
    }
)
_CONNECTORS = frozenset({"and", "of", "the", "in", "on", "for", "to"})


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One presentation role: display title, category, and its tree arcs."""

    role_uri: str
    title: str
    category: str
    family: str | None
    concept_count: int
    roots: tuple[str, ...]
    arcs: tuple[PresentationArc, ...]

    @property
    def concepts(self) -> tuple[str, ...]:
        """Distinct concepts in the role's tree, sorted."""
        seen = set()
        for arc in self.arcs:
            seen.add(arc.parent_qname)
            seen.add(arc.child_qname)
        return tuple(sorted(seen))


def build_catalog(kernel: FilingKernel) -> tuple[CatalogEntry, ...]:
    """Catalog the kernel's presentation roles in filed order."""
    arcs = kernel.presentation_arcs
    if not arcs:
        return ()
    by_role: dict[str, list[PresentationArc]] = {}
    for arc in arcs:
        if arc.role_uri:
            by_role.setdefault(arc.role_uri, []).append(arc)
    patterns = _slice_patterns()
    words, attested = _vocabulary(kernel, by_role)
    return tuple(
        _entry(kernel, role_uri, tuple(role_arcs), patterns, words, attested)
        for role_uri, role_arcs in by_role.items()
    )


@lru_cache(maxsize=64)
def _catalog_index(
    entries: tuple[CatalogEntry, ...],
) -> tuple[dict[str, CatalogEntry], dict[str, CatalogEntry], dict[str, CatalogEntry]]:
    """First-wins lookups by role URI, exact title, and casefolded title."""
    by_role: dict[str, CatalogEntry] = {}
    by_title: dict[str, CatalogEntry] = {}
    by_folded: dict[str, CatalogEntry] = {}
    for entry in entries:
        by_role.setdefault(entry.role_uri, entry)
        by_title.setdefault(entry.title, entry)
        by_folded.setdefault(entry.title.casefold(), entry)
    return by_role, by_title, by_folded


def catalog_get(
    entries: tuple[CatalogEntry, ...], role_or_title: str
) -> CatalogEntry | None:
    """Resolve one entry by role URI, else by title (exact, then casefolded)."""
    by_role, by_title, by_folded = _catalog_index(entries)
    found = by_role.get(role_or_title)
    if found is None:
        found = by_title.get(role_or_title)
    if found is None:
        found = by_folded.get(role_or_title.casefold())
    return found


def catalog_search(
    entries: tuple[CatalogEntry, ...], term: str
) -> tuple[CatalogEntry, ...]:
    """Entries whose title carries every token of the term."""
    wanted = {token.lower() for token in split_camel_case(term)}
    if not wanted:
        return ()
    return tuple(
        entry
        for entry in entries
        if wanted <= {piece.lower() for piece in entry.title.split()}
    )


def catalog_by_category(
    entries: tuple[CatalogEntry, ...], category: str
) -> tuple[CatalogEntry, ...]:
    """Entries in one category, in catalog order."""
    return tuple(entry for entry in entries if entry.category == category)


def catalog_frame(entries: tuple[CatalogEntry, ...]) -> pd.DataFrame:
    """Catalog as a DataFrame: title, category, concept count, role."""
    import pandas as pd

    return pd.DataFrame(
        [
            {
                "title": entry.title,
                "category": entry.category,
                "concept_count": entry.concept_count,
                "role": entry.role_uri,
            }
            for entry in entries
        ],
        columns=["title", "category", "concept_count", "role"],
    )


def _entry(
    kernel: FilingKernel,
    role_uri: str,
    arcs: tuple[PresentationArc, ...],
    patterns: tuple[dict, ...],
    words: frozenset[str],
    attested: frozenset[str],
) -> CatalogEntry:
    children = {arc.child_qname for arc in arcs}
    first_order: dict[str, float] = {}
    for arc in arcs:
        order = arc.order if arc.order is not None else 0.0
        if arc.parent_qname not in first_order or order < first_order[arc.parent_qname]:
            first_order[arc.parent_qname] = order
    roots = tuple(
        sorted(
            {arc.parent_qname for arc in arcs} - children,
            key=lambda qname: (first_order[qname], qname),
        )
    )
    family = None
    for root in roots:
        family = _root_family(kernel, root, patterns)
        if family is not None:
            break
    concepts = set()
    for arc in arcs:
        concepts.add(arc.parent_qname)
        concepts.add(arc.child_qname)
    return CatalogEntry(
        role_uri=role_uri,
        title=_role_title(role_uri, words, attested),
        category=_category(role_uri, roots, family),
        family=family,
        concept_count=len(concepts),
        roots=roots,
        arcs=arcs,
    )


def _category(role_uri: str, roots: tuple[str, ...], family: str | None) -> str:
    tokens = [token.lower() for token in split_camel_case(_role_tail(role_uri))]
    if family == "Cover" or "document" in tokens or "cover" in tokens:
        return DOCUMENT
    if any(split_concept_qname(root)[0] == "dei" for root in roots):
        return DOCUMENT
    if tokens and tokens[-1] in _DETAIL_SUFFIXES:
        return DISCLOSURE
    if family is not None or "statement" in tokens or "statements" in tokens:
        return STATEMENT
    return NOTE


def _root_family(
    kernel: FilingKernel, root: str, patterns: tuple[dict, ...]
) -> str | None:
    """Statement slice a root concept seeds, per the declared patterns."""
    namespace = split_concept_qname(root)[0]
    tokens = set(tokenize_fact_concept(root))
    atom = kernel.atom(root)
    head = atom.head if atom is not None else None
    for pattern in patterns:
        if pattern.get("namespace") and pattern["namespace"] != namespace:
            continue
        if pattern.get("head") and pattern["head"] != head:
            continue
        if not set(pattern.get("tokens_all", ())) <= tokens:
            continue
        return str(pattern["slice"])
    return None


def _slice_patterns() -> tuple[dict, ...]:
    """Declared statement-root patterns from the taxonomy data file."""
    path = resolve_xbrl_paths().default_statement_roots_path
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def _role_tail(role_uri: str) -> str:
    return role_uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _vocabulary(
    kernel: FilingKernel, by_role: dict[str, list[PresentationArc]]
) -> tuple[frozenset[str], frozenset[str]]:
    """Segmentation dictionaries: validated words, filing-attested tokens.
    Words are lexicon tokens plus the validated stop words; attested
    tokens are admitted as pieces only at 4+ chars (see _segment_word).
    """
    qnames = {fact.concept_qname for fact in kernel.facts}
    for arc in kernel.calculation_arcs:
        qnames.update((arc.parent_qname, arc.child_qname))
    for role_arcs in by_role.values():
        for arc in role_arcs:
            qnames.update((arc.parent_qname, arc.child_qname))
    attested = set()
    for qname in qnames:
        for token in split_camel_case(qname_local(qname)):
            if len(token) >= 2:
                attested.add(token.lower())
    words = set(_STOP_WORDS)
    lexicon = kernel.taxonomy.token_lexicon
    if lexicon is not None:
        for entry in lexicon.entries:
            for token in entry.phrase:
                if len(token) >= 2:
                    words.add(token.lower())
    return frozenset(words), frozenset(attested)


def _role_title(role_uri: str, words: frozenset[str], attested: frozenset[str]) -> str:
    tail = _role_tail(role_uri)
    tokens = list(split_camel_case(tail))
    if tokens and tokens[0].lower() == "role":
        tokens = tokens[1:]
        if len(tokens) > 1 and tokens[0].lower() in _CATEGORY_SEGMENTS:
            tokens = tokens[1:]
    parts: list[str] = []
    for token in tokens:
        if token.isupper() and len(token) >= 4:
            pieces = _segment_word(token.lower(), words, attested, whole_ok=True)
            if pieces is not None:
                parts.extend(piece.capitalize() for piece in pieces)
            else:
                parts.append(token.capitalize())
            continue
        if len(token) >= 6 and token.isalpha():
            pieces = _segment_word(token.lower(), words, attested)
            if pieces is not None:
                parts.extend(piece.capitalize() for piece in pieces)
                continue
        parts.append(token)
    titled = [
        part.lower() if index and part.lower() in _CONNECTORS else part
        for index, part in enumerate(parts)
    ]
    title = " ".join(titled)
    return title[:1].upper() + title[1:] if title else tail


def _segment_word(
    word: str,
    words: frozenset[str],
    attested: frozenset[str],
    *,
    whole_ok: bool = False,
) -> list[str] | None:
    """Segment a merged word by longest match, with backtracking.
    Pieces are lexicon/stop words or attested tokens of 4+ chars, each
    optionally consuming a plural s. None unless 2+ pieces, one content.
    """

    def accepted(piece: str) -> bool:
        if piece in words or (len(piece) >= 4 and piece in attested):
            return True
        if len(piece) >= 3 and piece[-1] == "s":
            base = piece[:-1]
            return base in words or (len(base) >= 4 and base in attested)
        return False

    memo: dict[tuple[int, bool], tuple[str, ...] | None] = {}

    def from_pos(pos: int, first: bool) -> tuple[str, ...] | None:
        if pos == len(word):
            return ()
        key = (pos, first)
        if key in memo:
            return memo[key]
        result = None
        longest = len(word) - pos - (1 if first else 0)
        for end in range(longest, 0, -1):
            piece = word[pos : pos + end]
            if accepted(piece):
                tail = from_pos(pos + end, False)
                if tail is not None:
                    result = (piece, *tail)
                    break
        memo[key] = result
        return result

    pieces = from_pos(0, not whole_ok)
    if pieces is None or len(pieces) < 2:
        return None
    if all(piece in _STOP_WORDS for piece in pieces):
        return None
    return list(pieces)
