"""BM25 ranking and exact/regex matching over the text index store.

Scores come from the index's stored corpus statistics; exact and regex
modes scan chunk text in DuckDB and carry no score.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from edgar_sec.infra.storage.duckdb import DuckDBError
from edgar_sec.infra.storage.text_index import TextIndexStore, tokenize_query

from .models import Coverage, SearchHit, SearchResult, SearchScope, TargetVerdict

_K1 = 1.2
_B = 0.75
_EXCERPT_RADIUS = 160
_MODES = ("bm25", "exact", "regex")


def _filter_sql(scope: SearchScope, params: list[object]) -> str:
    """WHERE clauses over the documents alias ``d``, values bound as params."""
    clauses: list[str] = []
    if scope.accessions:
        marks = ", ".join("?" for _ in scope.accessions)
        clauses.append(f"d.accession IN ({marks})")
        params.extend(scope.accessions)
    if scope.ciks:
        marks = ", ".join("?" for _ in scope.ciks)
        clauses.append(f"d.cik IN ({marks})")
        params.extend(scope.ciks)
    if scope.forms:
        marks = ", ".join("?" for _ in scope.forms)
        clauses.append(f"d.form IN ({marks})")
        params.extend(scope.forms)
    if scope.date_from is not None:
        clauses.append("d.filing_date >= ?")
        params.append(scope.date_from)
    if scope.date_to is not None:
        clauses.append("d.filing_date <= ?")
        params.append(scope.date_to)
    if scope.attachment_scope == "primary_only":
        clauses.append("d.document_role = 'primary'")
    elif scope.attachment_scope != "all_documents":
        raise ValueError(f"unknown attachment_scope: {scope.attachment_scope!r}")
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


def _excerpt(text: str, needle: str | None, pattern: re.Pattern[str] | None) -> str:
    """A slice of the stored chunk text around the first match."""
    start = 0
    if pattern is not None:
        match = pattern.search(text)
        if match is not None:
            start = match.start()
    elif needle:
        found = text.lower().find(needle.lower())
        if found >= 0:
            start = found
    low = max(0, start - _EXCERPT_RADIUS)
    high = min(len(text), start + _EXCERPT_RADIUS)
    return text[low:high]


def _coverage(con, store: TextIndexStore, scope: SearchScope) -> Coverage:  # noqa: ANN001, ANN202
    stats = store.corpus_stats() or {}
    params: list[object] = []
    where = _filter_sql(scope, params)
    row = con.execute(
        f"SELECT count(DISTINCT d.accession), count(*), "
        f"count(DISTINCT c.chunk_id) FROM documents d "
        f"JOIN chunks c ON c.payload_sha256 = d.payload_sha256{where}",
        params,
    ).fetchone()
    targets: list[TargetVerdict] = []
    for accession in scope.accessions:
        found = con.execute(
            "SELECT count(*) FROM documents WHERE accession = ?", [accession]
        ).fetchone()
        targets.append(TargetVerdict(accession, bool(found and found[0])))
    for cik in scope.ciks:
        found = con.execute(
            "SELECT count(*) FROM documents WHERE cik = ?", [cik]
        ).fetchone()
        targets.append(TargetVerdict(str(cik), bool(found and found[0])))
    return Coverage(
        index_present=True,
        source_snapshot_id=stats.get("source_snapshot_id"),  # type: ignore[arg-type]
        built_at=stats.get("built_at"),  # type: ignore[arg-type]
        accessions_searched=int(row[0]) if row else 0,
        documents_searched=int(row[1]) if row else 0,
        chunks_searched=int(row[2]) if row else 0,
        targets=tuple(targets),
    )


def _hit(row, excerpt: str, score: float | None) -> SearchHit:  # noqa: ANN001, ANN202
    return SearchHit(
        accession=str(row[0]),
        filename=str(row[1]),
        logical_document_id=str(row[2]) if row[2] is not None else None,
        document_role=str(row[3]) if row[3] is not None else None,
        section_name=str(row[4]) if row[4] is not None else None,
        note_label=str(row[5]) if row[5] is not None else None,
        start_line=int(row[6]),
        end_line=int(row[7]),
        excerpt=excerpt,
        score=score,
    )


_COLUMNS = (
    "d.accession, d.filename, d.logical_document_id, d.document_role, "
    "c.section_name, c.note_label, c.start_line, c.end_line, c.chunk_text"
)


def _bm25_hits(con, query: str, scope: SearchScope, limit: int) -> list[SearchHit]:  # noqa: ANN001, ANN202
    terms = tokenize_query(query)
    if not terms:
        return []
    stats_rows = con.execute(
        "SELECT term, chunk_frequency FROM term_stats WHERE term IN "
        f"({', '.join('?' for _ in terms)})",
        terms,
    ).fetchall()
    if not stats_rows:
        return []
    total_chunks_row = con.execute("SELECT chunk_count FROM corpus_stats").fetchone()
    total_chunks = float(total_chunks_row[0]) if total_chunks_row else 0.0
    avg_row = con.execute("SELECT avg_chunk_length FROM corpus_stats").fetchone()
    avg_length = float(avg_row[0]) if avg_row and avg_row[0] else 1.0
    con.execute("CREATE OR REPLACE TEMP TABLE query_terms (term VARCHAR, idf DOUBLE)")
    con.executemany(
        "INSERT INTO query_terms VALUES (?, ?)",
        [
            (
                str(term),
                math.log(1.0 + (total_chunks - float(df) + 0.5) / (float(df) + 0.5)),
            )
            for term, df in stats_rows
        ],
    )
    return _bm25_rows(con, scope, limit, avg_length, terms)


def _bm25_rows(
    con, scope: SearchScope, limit: int, avg_length: float, terms
) -> list[SearchHit]:  # noqa: ANN001, ANN202
    params: list[object] = []
    where = _filter_sql(scope, params)
    sql = (
        f"SELECT {_COLUMNS}, sum("
        f"p.term_frequency * (? + 1) / "
        f"(p.term_frequency + ? * (1 - ? + ? * p.chunk_length / ?)) "
        f"* qt.idf) AS score "
        f"FROM postings p "
        f"JOIN query_terms qt ON qt.term = p.term "
        f"JOIN chunks c ON c.chunk_id = p.chunk_id "
        f"JOIN documents d ON d.payload_sha256 = c.payload_sha256"
        f"{where} "
        f"GROUP BY ALL ORDER BY score DESC, d.accession, d.filename, c.start_line "
        f"LIMIT ?"
    )
    rows = con.execute(
        sql, [_K1, _K1, _B, _B, avg_length, *params, int(limit)]
    ).fetchall()
    hits: list[SearchHit] = []
    for row in rows:
        hits.append(_hit(row, _excerpt(str(row[8]), terms[0], None), float(row[9])))
    return hits


def _scan_hits(
    con, query: str, mode: str, scope: SearchScope, limit: int
) -> list[SearchHit]:  # noqa: ANN001, ANN202
    params: list[object] = []
    where = _filter_sql(scope, params)
    if mode == "exact":
        predicate = "contains(lower(c.chunk_text), lower(?))"
        params.insert(0, query)
        pattern = None
        needle: str | None = query
    else:
        predicate = "regexp_matches(c.chunk_text, ?)"
        params.insert(0, query)
        try:
            pattern = re.compile(query)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        needle = None
    sql = (
        f"SELECT {_COLUMNS} FROM chunks c "
        f"JOIN documents d ON d.payload_sha256 = c.payload_sha256 "
        f"WHERE {predicate}"
        f"{where.replace(' WHERE ', ' AND ', 1) if where else ''} "
        f"ORDER BY d.accession, d.filename, c.start_line LIMIT ?"
    )
    try:
        rows = con.execute(sql, [*params, int(limit)]).fetchall()
    except DuckDBError as exc:
        raise ValueError(f"invalid {mode} query: {exc}") from exc
    return [_hit(row, _excerpt(str(row[8]), needle, pattern), None) for row in rows]


def search_index(
    index_root: Path | str,
    query: str,
    *,
    mode: str = "bm25",
    scope: SearchScope | None = None,
    limit: int = 50,
) -> SearchResult:
    """Search the stored index; absence of the index is reported, not hidden."""
    if mode not in _MODES:
        raise ValueError(f"unknown search mode: {mode!r}")
    effective_scope = scope if scope is not None else SearchScope()
    store = TextIndexStore(index_root)
    if not store.exists():
        targets = tuple(
            TargetVerdict(target, False)
            for target in (
                *effective_scope.accessions,
                *(str(c) for c in effective_scope.ciks),
            )
        )
        return SearchResult(
            query=query,
            mode=mode,
            hits=(),
            coverage=Coverage(
                index_present=False,
                source_snapshot_id=None,
                built_at=None,
                accessions_searched=0,
                documents_searched=0,
                chunks_searched=0,
                targets=targets,
            ),
            not_in_corpus=tuple(t.target for t in targets),
        )
    con = store.connect()
    try:
        coverage = _coverage(con, store, effective_scope)
        if mode == "bm25":
            hits = _bm25_hits(con, query, effective_scope, limit)
        else:
            hits = _scan_hits(con, query, mode, effective_scope, limit)
    finally:
        con.close()
    not_in_corpus = tuple(t.target for t in coverage.targets if not t.covered)
    return SearchResult(
        query=query,
        mode=mode,
        hits=tuple(hits),
        coverage=coverage,
        not_in_corpus=not_in_corpus,
    )


__all__ = ["search_index"]
