"""Materialization of filing aggregates directly from SEC submissions JSON."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.filing_catalog.filters import (
    date_selection_matches,
    resolve_date_selection,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.sec_urls import archives_url, submissions_url
from edgar_sec.infra.sec_http.client import SecHttpClient


def materialize_from_submissions(
    cik: str | int | Cik,
    forms: str | Sequence[str] | None,
    dates: str | None,
    limit: int | None,
    factories: dict[str, Any],
    doc_cache: DocumentCache,
    client: SecHttpClient,
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
    date_sel = resolve_date_selection(dates) if dates else ()

    results: list[FilingAggregate] = []
    total = len(accessions)
    for idx in range(total):
        form_val = str(forms_list[idx]) if idx < len(forms_list) else ""
        if allowed_forms is not None and form_val not in allowed_forms:
            continue

        f_date = str(filing_dates[idx]) if idx < len(filing_dates) else ""
        if date_sel and not date_selection_matches(date_sel, f_date):
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
            fetcher=factories.get("fetcher"),
            cache_clearer=doc_cache.clear,
            zip_exporter=lambda filing, zpath: doc_cache.export_zip(
                zpath, accession=filing.accession.raw
            ),
            attachment_loader=factories.get("attachment_loader"),
            document_opener=factories.get("document_opener"),
            bundle_fetcher=factories.get("bundle_fetcher"),
            index_fetcher=factories.get("index_fetcher"),
            renderer=factories.get("renderer"),
        )
        results.append(agg)
        if limit is not None and len(results) >= limit:
            break

    return results


def collect_submissions_fallback(
    ciks: Sequence[Any],
    forms: str | Sequence[str] | None,
    dates: str | None,
    limit: int | None,
    factories: dict[str, Any],
    client: SecHttpClient,
    doc_cache: DocumentCache,
) -> tuple[FilingAggregate, ...]:
    """Collect filings across CIKs using SEC submissions API fallback."""
    aggregates: list[FilingAggregate] = []
    for c in ciks:
        on_the_fly = materialize_from_submissions(
            c, forms, dates, limit, factories, doc_cache, client
        )
        aggregates.extend(on_the_fly)
    if limit is not None:
        aggregates = aggregates[: int(limit)]
    return tuple(aggregates)
