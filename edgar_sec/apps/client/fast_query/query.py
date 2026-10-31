"""Fast-path catalog query execution via DuckDB direct scan."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa

from edgar_sec.apps.client.cache import DocumentCache, get_default_cache
from edgar_sec.apps.client.fast_query.loaders import (
    make_attachment_loader,
    make_bundle_fetcher,
    make_document_fetcher,
    make_document_opener,
    make_index_fetcher,
)
from edgar_sec.apps.client.fast_query.rendering import make_filing_renderer
from edgar_sec.apps.client.fast_query.submissions import collect_submissions_fallback
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.filing_catalog.filters import (
    AbsoluteDateClause,
    resolve_date_selection,
)
from edgar_sec.domain.identity import Cik
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.filing_catalog.paths import (
    TARGETS_DIR,
    resolve_filing_catalog_paths,
)


def query_catalog_fast(
    ciks: Sequence[str | int | Cik] | None = None,
    forms: str | Sequence[str] | None = None,
    dates: str | None = None,
    limit: int | None = None,
    *,
    operation: str | None = None,
    family_operations: dict[str, str] | None = None,
    artifacts_root: Path | str | None = None,
    cache: DocumentCache | None = None,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
) -> FilingsResult:
    """Execute direct DuckDB catalog scan and return hydrated FilingsResult."""
    catalog_paths = resolve_filing_catalog_paths(artifacts_root)
    found_files = sorted(
        {
            str(p)
            for p in catalog_paths.catalog_root.glob(f"**/{TARGETS_DIR}*/**/*.parquet")
        }
        | {
            str(p)
            for p in catalog_paths.catalog_root.glob(f"**/{TARGETS_DIR}*/*.parquet")
        }
    )
    targets_pattern = (
        found_files[0]
        if len(found_files) == 1
        else str(catalog_paths.catalog_root / "**" / TARGETS_DIR / "*.parquet")
    )

    doc_cache = cache if cache is not None else get_default_cache(artifacts_root)
    factories = {
        "fetcher": make_document_fetcher(doc_cache, http_client_factory),
        "cache_clearer": doc_cache.clear,
        "zip_exporter": lambda filing, zpath: doc_cache.export_zip(
            zpath, accession=filing.accession.raw
        ),
        "attachment_loader": make_attachment_loader(doc_cache, http_client_factory),
        "document_opener": make_document_opener(doc_cache, http_client_factory),
        "bundle_fetcher": make_bundle_fetcher(doc_cache, http_client_factory),
        "index_fetcher": make_index_fetcher(doc_cache, http_client_factory),
        "renderer": make_filing_renderer(
            doc_cache,
            http_client_factory,
            operation=operation,
            family_operations=family_operations,
        ),
    }

    if not found_files:
        items = ()
        if ciks:
            client = (
                http_client_factory()
                if http_client_factory is not None
                else SecHttpClient()
            )
            items = collect_submissions_fallback(
                ciks, forms, dates, limit, factories, client, doc_cache
            )
        return FilingsResult(
            run_id="fast-path",
            plan_id="fast-path",
            target_parquet_glob=targets_pattern,
            run_state_sqlite_path=doc_cache.db_path,
            artifacts_root=catalog_paths.artifacts_root,
            items=items,
        )

    clauses: list[str] = []
    params: list[Any] = [found_files]
    query_tables: dict[str, Any] | None = None
    join_clause = ""

    if ciks:
        cik_queries: list[Any] = []
        for c in ciks:
            if isinstance(c, Cik):
                cik_queries.extend([c.to_10digit(), str(c.value), c.value])
            else:
                s = str(c).strip()
                cik_queries.extend(
                    [
                        s.zfill(10),
                        s.lstrip("0") or "0",
                        int(s) if s.isdigit() else s,
                    ]
                )
        if len(ciks) <= 32:
            placeholders = ", ".join(["?"] * len(cik_queries))
            clauses.append(f"source_cik IN ({placeholders})")
            params.extend(cik_queries)
        else:
            distinct_ciks = sorted({str(x) for x in cik_queries})
            cik_table = pa.Table.from_arrays(
                [pa.array(distinct_ciks, type=pa.string())],
                names=["filter_cik"],
            )
            query_tables = {"_target_ciks": cik_table}
            join_clause = "SEMI JOIN _target_ciks ON CAST(source_cik AS VARCHAR) = _target_ciks.filter_cik"

    if forms:
        form_list = [forms] if isinstance(forms, str) else list(forms)
        placeholders = ", ".join(["?"] * len(form_list))
        clauses.append(f"form IN ({placeholders})")
        params.extend(form_list)

    if dates:
        date_sel = resolve_date_selection(dates)
        for clause in date_sel:
            if isinstance(clause, AbsoluteDateClause):
                if clause.start_date:
                    clauses.append("filing_date >= ?")
                    params.append(clause.iso_start)
                if clause.end_date:
                    clauses.append("filing_date <= ?")
                    params.append(clause.iso_end)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_sql = f"LIMIT {int(limit)}" if limit is not None else ""

    url_expr = "primary_doc_url"
    if found_files:
        try:
            import pyarrow.parquet as pq

            names = set(pq.read_schema(found_files[0]).names)
            if "primary_doc_url" not in names and "archive_url" in names:
                url_expr = "archive_url AS primary_doc_url"
        except Exception:
            pass

    query = f"""
        SELECT DISTINCT
            accession,
            source_cik,
            form,
            filing_date,
            report_date,
            primary_document,
            {url_expr}
        FROM read_parquet(?)
        {join_clause}
        {where_sql}
        ORDER BY filing_date DESC, accession DESC
        {limit_sql}
    """

    has_matches = False
    if ciks:
        with connect() as con:
            try:
                if query_tables:
                    for tname, tbl in query_tables.items():
                        con.register(tname, tbl)
                check_sql = (
                    f"SELECT 1 FROM read_parquet(?) {join_clause} {where_sql} LIMIT 1"
                )
                has_matches = con.execute(check_sql, params).fetchone() is not None
            except Exception:
                has_matches = False
    else:
        has_matches = True

    if not has_matches and ciks:
        client = (
            http_client_factory()
            if http_client_factory is not None
            else SecHttpClient()
        )
        items = collect_submissions_fallback(
            ciks, forms, dates, limit, factories, client, doc_cache
        )
        return FilingsResult(
            run_id="fast-path",
            plan_id="fast-path",
            target_parquet_glob=targets_pattern,
            run_state_sqlite_path=doc_cache.db_path,
            artifacts_root=catalog_paths.artifacts_root,
            items=items,
        )

    return FilingsResult(
        run_id="fast-path",
        plan_id="fast-path",
        target_parquet_glob=targets_pattern,
        run_state_sqlite_path=doc_cache.db_path,
        artifacts_root=catalog_paths.artifacts_root,
        query_backed=True,
        query_sql=query,
        query_params=tuple(params),
        query_tables=query_tables,
        query_factories=factories,
        items=None,
    )
