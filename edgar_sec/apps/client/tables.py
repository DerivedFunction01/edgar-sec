"""In-memory PyArrow table builders for filing aggregate collections.

Serializes planned and acquired filing aggregates into columnar PyArrow tables.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa

from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.filing_catalog.document_names import is_primary_exhibit_filename
from edgar_sec.engine.xbrl.discovery.discovery import classify_linkbase


def is_exhibit_attachment(doc_type: str, filename: str) -> bool:
    """Classify whether document represents an SEC exhibit."""
    dt = doc_type.upper()
    return dt.startswith("EX-") or is_primary_exhibit_filename(filename)


def build_catalog_table(filings: Sequence[FilingAggregate]) -> pa.Table:
    """Build Arrow catalog table from filing aggregates."""
    accessions = [f.accession.value for f in filings]
    forms = [f.form for f in filings]
    filing_dates = [f.filing_date for f in filings]
    report_dates = [f.report_date or "" for f in filings]
    primary_docs = [
        f.primary_document_path
        or (f.primary_document_url.split("/")[-1] if f.primary_document_url else "")
        for f in filings
    ]
    primary_urls = [f.primary_document_url or "" for f in filings]
    return pa.Table.from_arrays(
        [
            pa.array(accessions, type=pa.string()),
            pa.array(forms, type=pa.string()),
            pa.array(filing_dates, type=pa.string()),
            pa.array(report_dates, type=pa.string()),
            pa.array(primary_docs, type=pa.string()),
            pa.array(primary_urls, type=pa.string()),
        ],
        names=[
            "accession",
            "form",
            "filing_date",
            "report_date",
            "primary_document",
            "primary_doc_url",
        ],
    )


def build_index_table(filings: Sequence[FilingAggregate]) -> pa.Table:
    """Build Arrow index/attachments table from filing aggregates."""
    accs: list[str] = []
    seqs: list[int] = []
    dtypes: list[str] = []
    fnames: list[str] = []
    descs: list[str] = []
    sizes: list[int] = []
    urls: list[str] = []
    is_exs: list[bool] = []

    for f in filings:
        atts = f.get_attachments()
        for idx, a in enumerate(atts, 1):
            accs.append(f.accession.value)
            seq_val = idx
            try:
                if a.attachment_id and a.attachment_id.isdigit():
                    seq_val = int(a.attachment_id)
            except Exception:
                pass
            seqs.append(seq_val)
            dtypes.append(a.document_type)
            fnames.append(a.filename)
            descs.append(a.description or "")
            sizes.append(a.size or 0)
            urls.append(a.url)
            is_exs.append(is_exhibit_attachment(a.document_type, a.filename))

    return pa.Table.from_arrays(
        [
            pa.array(accs, type=pa.string()),
            pa.array(seqs, type=pa.int32()),
            pa.array(dtypes, type=pa.string()),
            pa.array(fnames, type=pa.string()),
            pa.array(descs, type=pa.string()),
            pa.array(sizes, type=pa.int64()),
            pa.array(urls, type=pa.string()),
            pa.array(is_exs, type=pa.bool_()),
        ],
        names=[
            "accession",
            "sequence",
            "document_type",
            "filename",
            "description",
            "size",
            "url",
            "is_exhibit",
        ],
    )


def build_exhibits_table(
    filings: Sequence[FilingAggregate], types: Sequence[str] | str = ()
) -> pa.Table:
    """Build Arrow exhibits table from filing aggregates."""
    filter_types = (
        {types.upper()}
        if isinstance(types, str) and types
        else {t.upper() for t in types}
        if types
        else None
    )
    accs: list[str] = []
    forms: list[str] = []
    dtypes: list[str] = []
    descs: list[str] = []
    fnames: list[str] = []
    sizes: list[int] = []
    urls: list[str] = []

    for f in filings:
        for ex in f.exhibits:
            dt = ex.document_type
            if filter_types is not None:
                matched = False
                canon_dt = dt.upper()
                for ft in filter_types:
                    canon_ft = f"EX-{ft}" if not ft.startswith("EX-") else ft
                    if (
                        canon_dt == canon_ft
                        or canon_dt == ft
                        or canon_dt.startswith(f"{canon_ft}.")
                    ):
                        matched = True
                        break
                if not matched:
                    continue
            accs.append(f.accession.value)
            forms.append(f.form)
            dtypes.append(dt)
            descs.append(ex.description or "")
            fnames.append(ex.filename)
            sizes.append(ex.size or 0)
            urls.append(ex.url)

    return pa.Table.from_arrays(
        [
            pa.array(accs, type=pa.string()),
            pa.array(forms, type=pa.string()),
            pa.array(dtypes, type=pa.string()),
            pa.array(descs, type=pa.string()),
            pa.array(fnames, type=pa.string()),
            pa.array(sizes, type=pa.int64()),
            pa.array(urls, type=pa.string()),
        ],
        names=[
            "accession",
            "form",
            "document_type",
            "description",
            "filename",
            "size",
            "url",
        ],
    )


def build_linkbases_table(filings: Sequence[FilingAggregate]) -> pa.Table:
    """Build Arrow linkbases table from filing aggregates."""
    accs: list[str] = []
    forms: list[str] = []
    lb_types: list[str] = []
    dtypes: list[str] = []
    fnames: list[str] = []
    urls: list[str] = []

    for f in filings:
        for lb in f.linkbases:
            accs.append(f.accession.value)
            forms.append(f.form)
            lb_type = classify_linkbase(
                lb.document_type or "",
                lb.filename or "",
                lb.description or "",
            )
            lb_types.append(lb_type.value if lb_type is not None else "")
            dtypes.append(lb.document_type)
            fnames.append(lb.filename)
            urls.append(lb.url)

    return pa.Table.from_arrays(
        [
            pa.array(accs, type=pa.string()),
            pa.array(forms, type=pa.string()),
            pa.array(lb_types, type=pa.string()),
            pa.array(dtypes, type=pa.string()),
            pa.array(fnames, type=pa.string()),
            pa.array(urls, type=pa.string()),
        ],
        names=[
            "accession",
            "form",
            "linkbase_type",
            "document_type",
            "filename",
            "url",
        ],
    )


def build_payload_table(filings: Sequence[FilingAggregate]) -> pa.Table:
    """Build Arrow payload/staged table from filing aggregates."""
    tids: list[str] = []
    accs: list[str] = []
    outcomes: list[str] = []
    attempts: list[int] = []
    durations: list[int] = []
    shas: list[str] = []
    sizes: list[int] = []
    paths: list[str] = []

    for idx, f in enumerate(filings, 1):
        tids.append(f"tgt_{idx:03d}")
        accs.append(f.accession.value)
        has_body = (
            f.primary_storage_path is not None and f.primary_storage_path.is_file()
        ) or f.fetcher is not None
        outcomes.append("acquired" if has_body else "planned")
        attempts.append(1)
        durations.append(0)
        shas.append(f.primary_sha256 or "")
        b_size = 0
        if f.primary_storage_path and f.primary_storage_path.is_file():
            try:
                b_size = f.primary_storage_path.stat().st_size
            except OSError:
                b_size = 0
        sizes.append(b_size)
        paths.append(str(f.primary_storage_path) if f.primary_storage_path else "")

    return pa.Table.from_arrays(
        [
            pa.array(tids, type=pa.string()),
            pa.array(accs, type=pa.string()),
            pa.array(outcomes, type=pa.string()),
            pa.array(attempts, type=pa.int32()),
            pa.array(durations, type=pa.int64()),
            pa.array(shas, type=pa.string()),
            pa.array(sizes, type=pa.int64()),
            pa.array(paths, type=pa.string()),
        ],
        names=[
            "target_id",
            "accession",
            "outcome",
            "attempt_count",
            "duration_ms",
            "body_sha256",
            "body_byte_size",
            "body_storage_path",
        ],
    )


def build_joined_table(filings: Sequence[FilingAggregate]) -> pa.Table:
    """Build consolidated Arrow joined table from filing aggregates."""
    accs: list[str] = []
    forms: list[str] = []
    filing_dates: list[str] = []
    primary_docs: list[str] = []
    outcomes: list[str] = []
    sizes: list[int | None] = []
    paths: list[str | None] = []
    urls: list[str] = []

    for f in filings:
        accs.append(f.accession.value)
        forms.append(f.form)
        filing_dates.append(f.filing_date)
        pdoc = f.primary_document_path or (
            f.primary_document_url.split("/")[-1] if f.primary_document_url else ""
        )
        primary_docs.append(pdoc)
        has_body = (
            f.primary_storage_path is not None and f.primary_storage_path.is_file()
        ) or f.fetcher is not None
        outcomes.append("acquired" if has_body else "planned")
        b_size = None
        if f.primary_storage_path and f.primary_storage_path.is_file():
            try:
                b_size = f.primary_storage_path.stat().st_size
            except OSError:
                pass
        sizes.append(b_size)
        paths.append(str(f.primary_storage_path) if f.primary_storage_path else None)
        urls.append(f.primary_document_url or "")

    return pa.Table.from_arrays(
        [
            pa.array(accs, type=pa.string()),
            pa.array(forms, type=pa.string()),
            pa.array(filing_dates, type=pa.string()),
            pa.array(primary_docs, type=pa.string()),
            pa.array(outcomes, type=pa.string()),
            pa.array(sizes, type=pa.int64()),
            pa.array(paths, type=pa.string()),
            pa.array(urls, type=pa.string()),
        ],
        names=[
            "accession",
            "form",
            "filing_date",
            "primary_document",
            "outcome",
            "body_byte_size",
            "body_storage_path",
            "target_url",
        ],
    )


__all__ = [
    "build_catalog_table",
    "build_exhibits_table",
    "build_index_table",
    "build_joined_table",
    "build_linkbases_table",
    "build_payload_table",
    "is_exhibit_attachment",
]
