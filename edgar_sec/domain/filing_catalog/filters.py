"""Filter vocabulary shared by deterministic planning and selection policy.

This module holds only vocabulary and pure normalization: the closed set of
amendment policies, the default suffix set, and the suffix normalizer. It is
Layer 1 because two different layers need to agree on it --

* ``pipelines.filing_catalog.planner`` for deterministic planning, and
* ``engine.selection.policy.SelectionPolicy`` for Stage B selection.

Stage A originally kept this vocabulary in ``pipelines/filing_catalog/filters.py``
alongside the two SQL builders. Stage B could not reuse it: the layer graph is
acyclic downward-only, so Layer 3 (``engine``) may not import Layer 4
(``pipelines``). Rather than restate ``AMENDMENT_POLICIES`` in the selection
policy -- two closed sets that must never disagree about what ``original``
means -- the vocabulary moved down here, and the SQL builders moved down with
it to ``infra.storage.duckdb_catalog``.

v1 built its suffix predicate by interpolating both the column name and each
suffix straight into a SQL string literal, and ``normalize_suffixes`` only
lower-cased and de-dotted, so a suffix containing a quote could terminate the
literal. v2 rejects any suffix outside a conservative allowlist up front, which
fails loudly at the call site instead of producing malformed or injected SQL.
"""

from __future__ import annotations

import re

# Suffixes are user input arriving from a CLI flag or a policy document. Real SEC
# document names use letters, digits, and dots (``0001.htm`` is a real stub
# suffix), so the allowlist covers exactly that and rejects everything quote- or
# comment-shaped.
_SUFFIX_RE = re.compile(r"^[a-z0-9][a-z0-9.]*$")

DEFAULT_AMENDMENT = "both"
AMENDMENT_POLICIES = ("both", "original", "amendments")
DEFAULT_DOCUMENT_SUFFIXES: tuple[str, ...] = ()


def normalize_suffixes(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Lower-case, de-dot, de-duplicate, and validate document suffixes.

    Order is preserved because a plan's recorded suffix list participates in
    the plan identity hash; de-duplication keeps that hash stable when a caller
    repeats a suffix.
    """
    normalized: list[str] = []
    for suffix in values:
        if not isinstance(suffix, str):
            raise ValueError(f"suffix must be a string, got {type(suffix).__name__}")
        token = suffix.strip().lower().lstrip(".")
        if not token:
            continue
        if not _SUFFIX_RE.match(token):
            raise ValueError(
                f"invalid document suffix {suffix!r}; expected letters, digits, "
                "or dots only"
            )
        if token not in normalized:
            normalized.append(token)
    return tuple(normalized)


__all__ = [
    "AMENDMENT_POLICIES",
    "DEFAULT_AMENDMENT",
    "DEFAULT_DOCUMENT_SUFFIXES",
    "normalize_suffixes",
]
