"""Facade search over our own acquired holdings, via the text index.

This surface answers over the corpus the index was built from; the SEC's
own full-text index is a different surface and is never consulted here.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.text_search.engine import search_index
from edgar_sec.engine.text_search.models import SearchResult, SearchScope
from edgar_sec.infra.storage.text_index import default_index_root

__all__ = ["search_documents"]


def search_documents(
    query: str,
    *,
    mode: str = "bm25",
    artifacts_root: Path | str | None = None,
    index_root: Path | str | None = None,
    accessions: tuple[str, ...] = (),
    ciks: tuple[int, ...] = (),
    forms: tuple[str, ...] = (),
    date_from: str | None = None,
    date_to: str | None = None,
    attachment_scope: str = "all_documents",
    limit: int = 50,
) -> SearchResult:
    """Search the stored index; every result carries its coverage block."""
    root = (
        Path(index_root)
        if index_root is not None
        else default_index_root(artifacts_root)
    )
    scope = SearchScope(
        accessions=tuple(accessions),
        ciks=tuple(ciks),
        forms=tuple(forms),
        date_from=date_from,
        date_to=date_to,
        attachment_scope=attachment_scope,
    )
    return search_index(root, query, mode=mode, scope=scope, limit=limit)
