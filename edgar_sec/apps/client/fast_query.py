"""Fast-path catalog query engine for sub-50ms filing discovery and hydration."""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.cache import DocumentCache, get_default_cache
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.sec_urls import (
    accession_hyphenated,
    archives_url,
    full_submission_url_for,
    index_url_for,
    submissions_url,
)
from edgar_sec.engine.forms.render import render_filing
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.filing_catalog.paths import (
    resolve_filing_catalog_paths,
    TARGETS_DIR,
)


def _detect_content_type(filename: str) -> str:
    guess, _ = mimetypes.guess_type(filename)
    return guess or "application/octet-stream"


def _resolve_primary_filename(filing: FilingAggregate) -> str:
    if filing.primary_document_path:
        return Path(filing.primary_document_path).name
    if filing.primary_document_url:
        leaf = filing.primary_document_url.rsplit("/", 1)[-1]
        if leaf:
            return leaf
    return f"{accession_hyphenated(filing.accession.value)}.txt"


def _resolve_primary_url(filing: FilingAggregate) -> str:
    if filing.primary_document_url:
        return filing.primary_document_url
    fname = _resolve_primary_filename(filing)
    if fname.endswith(".txt"):
        return full_submission_url_for(
            str(filing.primary_cik.value), filing.accession.value
        )
    return archives_url(filing.primary_cik.value, filing.accession.value, fname)


def _make_document_fetcher(
    cache: DocumentCache,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
) -> Callable[[FilingAggregate], bytes | None]:
    """Create a lazy document fetcher closure bound to cache and HTTP client."""
    client_holder: list[SecHttpClient | None] = [None]

    def _get_client() -> SecHttpClient:
        if client_holder[0] is None:
            if http_client_factory is not None:
                client_holder[0] = http_client_factory()
            else:
                client_holder[0] = SecHttpClient()
        return client_holder[0]

    def _fetch(filing: FilingAggregate) -> bytes | None:
        filename = _resolve_primary_filename(filing)
        acc_str = filing.accession.value
        cached = cache.get(acc_str, filename)
        if cached is not None:
            return cached

        url = _resolve_primary_url(filing)
        if not url:
            return None

        client = _get_client()
        fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
        if fetch_fn is None:
            return None
        response_bytes = fetch_fn(url)
        if response_bytes is not None:
            c_type = _detect_content_type(filename)
            cache.put(
                accession=acc_str,
                cik=filing.primary_cik.value,
                form=filing.form,
                filename=filename,
                content=response_bytes,
                content_type=c_type,
            )
        return response_bytes

    return _fetch


def _make_attachment_loader(
    doc_cache: DocumentCache,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
) -> Callable[[FilingAggregate], tuple[FilingAttachment, ...]]:
    """Create a lazy attachment loader closure querying the -index.html page."""
    from edgar_sec.domain.document_inventory.models import (
        IndexPageInput,
        ParsedIndexPage,
    )
    from edgar_sec.domain.sec_urls import index_url_for
    from edgar_sec.engine.index_pages.parser import parse_html_index

    client_holder: list[SecHttpClient | None] = [None]

    def _get_client() -> SecHttpClient:
        if client_holder[0] is None:
            if http_client_factory is not None:
                client_holder[0] = http_client_factory()
            else:
                client_holder[0] = SecHttpClient()
        return client_holder[0]

    def _load(filing: FilingAggregate) -> tuple[FilingAttachment, ...]:
        fname = f"{filing.accession.raw}-index.html"
        html_bytes = doc_cache.get(filing.accession.raw, fname)
        url = index_url_for(filing.accession, filing.primary_cik)
        if html_bytes is None:
            client = _get_client()
            fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
            if fetch_fn is None:
                return ()
            try:
                html_bytes = fetch_fn(url)
            except Exception:
                return ()
            if html_bytes:
                doc_cache.put(
                    accession=filing.accession.raw,
                    cik=str(filing.primary_cik.value),
                    form=filing.form,
                    filename=fname,
                    content=html_bytes,
                    content_type="text/html",
                )
        if not html_bytes:
            return ()
        outcome = parse_html_index(
            IndexPageInput(
                accession=filing.accession,
                source_url=url,
                response_bytes=html_bytes,
            )
        )
        if not isinstance(outcome, ParsedIndexPage):
            return ()

        def _make_att_fetcher(
            target_url: str, fname: str
        ) -> Callable[[FilingAttachment], bytes | None]:
            def _fetch_att(_att: FilingAttachment) -> bytes | None:
                cached = doc_cache.get(filing.accession.raw, fname)
                if cached is not None:
                    return cached
                if not target_url:
                    return None
                cli = _get_client()
                fn = getattr(cli, "get_bytes", getattr(cli, "get", None))
                if fn is None:
                    return None
                data = fn(target_url)
                if data:
                    doc_cache.put(
                        accession=filing.accession.raw,
                        cik=str(filing.primary_cik.value),
                        form=filing.form,
                        filename=fname,
                        content=data,
                        content_type=_detect_content_type(fname),
                    )
                    return data
                return None

            return _fetch_att

        attachments: list[FilingAttachment] = []
        for entry in outcome.entries:
            fname = entry.filename or ""
            a_url = entry.archive_url or ""
            attachments.append(
                FilingAttachment(
                    attachment_id=str(entry.sequence or fname or ""),
                    document_type=entry.document_type or "",
                    filename=fname,
                    url=a_url,
                    size=entry.byte_size,
                    description=entry.description,
                    fetcher=_make_att_fetcher(a_url, fname) if a_url else None,
                )
            )
        return tuple(attachments)

    return _load


def _make_document_opener(
    doc_cache: DocumentCache,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
) -> Callable[[FilingAggregate, str], bytes | None]:
    client_holder: list[SecHttpClient | None] = [None]

    def _get_client() -> SecHttpClient:
        if client_holder[0] is None:
            client_holder[0] = (
                http_client_factory()
                if http_client_factory is not None
                else SecHttpClient()
            )
        return client_holder[0]

    def _open(filing: FilingAggregate, filename: str) -> bytes | None:
        cached = doc_cache.get(filing.accession.raw, filename)
        if cached is not None:
            return cached
        url = archives_url(filing.primary_cik.value, filing.accession.raw, filename)
        client = _get_client()
        fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
        if fetch_fn is None:
            return None
        data = fetch_fn(url)
        if data:
            doc_cache.put(
                accession=filing.accession.raw,
                cik=str(filing.primary_cik.value),
                form=filing.form,
                filename=filename,
                content=data,
                content_type=_detect_content_type(filename),
            )
            return data
        return None

    return _open


def _make_bundle_fetcher(
    doc_cache: DocumentCache,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
) -> Callable[[FilingAggregate], bytes | None]:
    client_holder: list[SecHttpClient | None] = [None]

    def _get_client() -> SecHttpClient:
        if client_holder[0] is None:
            client_holder[0] = (
                http_client_factory()
                if http_client_factory is not None
                else SecHttpClient()
            )
        return client_holder[0]

    def _fetch(filing: FilingAggregate) -> bytes | None:
        fname = f"{filing.accession.raw}.txt"
        cached = doc_cache.get(filing.accession.raw, fname)
        if cached is not None:
            return cached
        url = full_submission_url_for(
            str(filing.primary_cik.value), filing.accession.raw
        )
        client = _get_client()
        fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
        if fetch_fn is None:
            return None
        data = fetch_fn(url)
        if data:
            doc_cache.put(
                accession=filing.accession.raw,
                cik=str(filing.primary_cik.value),
                form=filing.form,
                filename=fname,
                content=data,
                content_type="text/plain",
            )
            return data
        return None

    return _fetch


def _make_index_fetcher(
    doc_cache: DocumentCache,
    http_client_factory: Callable[[], SecHttpClient] | None = None,
) -> Callable[[FilingAggregate], str | None]:
    client_holder: list[SecHttpClient | None] = [None]

    def _get_client() -> SecHttpClient:
        if client_holder[0] is None:
            client_holder[0] = (
                http_client_factory()
                if http_client_factory is not None
                else SecHttpClient()
            )
        return client_holder[0]

    def _fetch(filing: FilingAggregate) -> str | None:
        fname = f"{filing.accession.raw}-index.html"
        cached = doc_cache.get(filing.accession.raw, fname)
        if cached is not None:
            return cached.decode("utf-8", errors="replace")
        url = index_url_for(filing.accession, filing.primary_cik)
        client = _get_client()
        fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
        if fetch_fn is None:
            return None
        data = fetch_fn(url)
        if data:
            doc_cache.put(
                accession=filing.accession.raw,
                cik=str(filing.primary_cik.value),
                form=filing.form,
                filename=fname,
                content=data,
                content_type="text/html",
            )
            return data.decode("utf-8", errors="replace")
        return None

    return _fetch


def _materialize_from_submissions(
    cik: str | int | Cik,
    forms: str | Sequence[str] | None,
    dates: str | None,
    limit: int | None,
    fetcher: Callable[[FilingAggregate], bytes | None],
    doc_cache: DocumentCache,
    client: SecHttpClient,
    attachment_loader: (
        Callable[[FilingAggregate], tuple[FilingAttachment, ...]] | None
    ) = None,
    document_opener: Callable[[FilingAggregate, str], bytes | None] | None = None,
    bundle_fetcher: Callable[[FilingAggregate], bytes | None] | None = None,
    index_fetcher: Callable[[FilingAggregate], str | None] | None = None,
    renderer: Callable[[FilingAggregate], str | bytes | None] | None = None,
) -> list[FilingAggregate]:
    """Materialize filing aggregates on-the-fly from SEC submissions JSON."""
    cik_inst = cik if isinstance(cik, Cik) else Cik.from_raw(cik)
    url = submissions_url(cik_inst.to_10digit())
    fetch_fn = getattr(client, "get_bytes", getattr(client, "get", None))
    if fetch_fn is None:
        return []
    data = fetch_fn(url)
    if not data:
        return []

    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        return []

    recent = payload.get("filings", {}).get("recent", {})
    if not recent:
        return []

    accessions = recent.get("accessionNumber", [])
    forms_list = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])

    allowed_forms = {forms} if isinstance(forms, str) else set(forms) if forms else None

    results: list[FilingAggregate] = []
    total = len(accessions)
    for idx in range(total):
        form_val = str(forms_list[idx]) if idx < len(forms_list) else ""
        if allowed_forms is not None and form_val not in allowed_forms:
            continue

        f_date = str(filing_dates[idx]) if idx < len(filing_dates) else ""
        if dates and not f_date.startswith(dates):
            continue

        acc_str = str(accessions[idx])
        acc = AccessionNumber.from_any(acc_str)
        r_date = str(report_dates[idx]) if idx < len(report_dates) else None
        p_doc = str(primary_docs[idx]) if idx < len(primary_docs) else ""
        p_url = archives_url(cik_inst.value, acc.raw, p_doc) if p_doc else None

        agg = FilingAggregate(
            accession=acc,
            primary_cik=cik_inst,
            ciks=(cik_inst,),
            form=form_val,
            filing_date=f_date,
            report_date=r_date,
            primary_document_path=p_doc,
            primary_document_url=p_url,
            fetcher=fetcher,
            cache_clearer=doc_cache.clear,
            zip_exporter=lambda filing, zpath: doc_cache.export_zip(
                zpath, accession=filing.accession.raw
            ),
            attachment_loader=attachment_loader,
            document_opener=document_opener,
            bundle_fetcher=bundle_fetcher,
            index_fetcher=index_fetcher,
            renderer=renderer,
        )
        results.append(agg)
        if limit is not None and len(results) >= limit:
            break

    return results


def query_catalog_fast(
    ciks: Sequence[str | int | Cik] | None = None,
    forms: str | Sequence[str] | None = None,
    dates: str | None = None,
    limit: int | None = None,
    *,
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
    fetcher = _make_document_fetcher(doc_cache, http_client_factory)
    attachment_loader = _make_attachment_loader(doc_cache, http_client_factory)
    document_opener = _make_document_opener(doc_cache, http_client_factory)
    bundle_fetcher = _make_bundle_fetcher(doc_cache, http_client_factory)
    index_fetcher = _make_index_fetcher(doc_cache, http_client_factory)

    aggregates: list[FilingAggregate] = []

    if not found_files:
        if ciks:
            client = (
                http_client_factory()
                if http_client_factory is not None
                else SecHttpClient()
            )
            for c in ciks:
                on_the_fly = _materialize_from_submissions(
                    cik=c,
                    forms=forms,
                    dates=dates,
                    limit=limit,
                    fetcher=fetcher,
                    doc_cache=doc_cache,
                    client=client,
                    attachment_loader=attachment_loader,
                    document_opener=document_opener,
                    bundle_fetcher=bundle_fetcher,
                    index_fetcher=index_fetcher,
                    renderer=render_filing,
                )
                aggregates.extend(on_the_fly)
            if limit is not None:
                aggregates = aggregates[: int(limit)]
        return FilingsResult(
            run_id="fast-path",
            plan_id="fast-path",
            target_parquet_glob=targets_pattern,
            run_state_sqlite_path=doc_cache.db_path,
            artifacts_root=catalog_paths.artifacts_root,
            items=tuple(aggregates),
        )

    clauses: list[str] = []
    params: list[Any] = [found_files]

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
        placeholders = ", ".join(["?"] * len(cik_queries))
        clauses.append(f"source_cik IN ({placeholders})")
        params.extend(cik_queries)

    if forms:
        form_list = [forms] if isinstance(forms, str) else list(forms)
        placeholders = ", ".join(["?"] * len(form_list))
        clauses.append(f"form IN ({placeholders})")
        params.extend(form_list)

    if dates:
        clauses.append("filing_date LIKE ?")
        params.append(f"{dates}%")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_sql = f"LIMIT {int(limit)}" if limit is not None else ""

    query = f"""
        SELECT DISTINCT
            accession,
            source_cik,
            form,
            filing_date,
            report_date,
            primary_document,
            primary_doc_url
        FROM read_parquet(?)
        {where_sql}
        ORDER BY filing_date DESC, accession DESC
        {limit_sql}
    """

    with connect() as con:
        try:
            rows = con.execute(query, params).fetchall()
        except Exception:
            rows = []

    for acc_str, cik_val, form_val, f_date, r_date, p_doc, p_url in rows:
        acc = AccessionNumber.from_any(acc_str)
        cik_inst = Cik.from_raw(cik_val)
        agg = FilingAggregate(
            accession=acc,
            primary_cik=cik_inst,
            ciks=(cik_inst,),
            form=str(form_val),
            filing_date=str(f_date or ""),
            report_date=str(r_date) if r_date else None,
            primary_document_path=str(p_doc or ""),
            primary_document_url=str(p_url) if p_url else None,
            fetcher=fetcher,
            cache_clearer=doc_cache.clear,
            zip_exporter=lambda filing, zpath: doc_cache.export_zip(
                zpath, accession=filing.accession.raw
            ),
            attachment_loader=attachment_loader,
            document_opener=document_opener,
            bundle_fetcher=bundle_fetcher,
            index_fetcher=index_fetcher,
            renderer=render_filing,
        )
        aggregates.append(agg)

    if not aggregates and ciks:
        client = (
            http_client_factory()
            if http_client_factory is not None
            else SecHttpClient()
        )
        for c in ciks:
            on_the_fly = _materialize_from_submissions(
                cik=c,
                forms=forms,
                dates=dates,
                limit=limit,
                fetcher=fetcher,
                doc_cache=doc_cache,
                client=client,
                attachment_loader=attachment_loader,
                document_opener=document_opener,
                bundle_fetcher=bundle_fetcher,
                index_fetcher=index_fetcher,
                renderer=render_filing,
            )
            aggregates.extend(on_the_fly)
        if limit is not None:
            aggregates = aggregates[: int(limit)]

    return FilingsResult(
        run_id="fast-path",
        plan_id="fast-path",
        target_parquet_glob=targets_pattern,
        run_state_sqlite_path=doc_cache.db_path,
        artifacts_root=catalog_paths.artifacts_root,
        items=tuple(aggregates),
    )
