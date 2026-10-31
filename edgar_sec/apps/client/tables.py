"""In-memory PyArrow table builders for filing aggregate collections.

Serializes planned and acquired filing aggregates into columnar PyArrow tables.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import pyarrow as pa

from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.filing_catalog.document_names import is_primary_exhibit_filename
from edgar_sec.engine.xbrl.discovery.discovery import classify_linkbase
from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_READ_BATCH_SIZE


def is_exhibit_attachment(doc_type: str, filename: str) -> bool:
    """Classify whether document represents an SEC exhibit."""
    dt = doc_type.upper()
    return dt.startswith("EX-") or is_primary_exhibit_filename(filename)


CATALOG_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("report_date", pa.string()),
        ("primary_document", pa.string()),
        ("primary_doc_url", pa.string()),
    ]
)

INDEX_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("sequence", pa.int32()),
        ("document_type", pa.string()),
        ("filename", pa.string()),
        ("description", pa.string()),
        ("size", pa.int64()),
        ("url", pa.string()),
        ("is_exhibit", pa.bool_()),
    ]
)

EXHIBITS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("form", pa.string()),
        ("document_type", pa.string()),
        ("description", pa.string()),
        ("filename", pa.string()),
        ("size", pa.int64()),
        ("url", pa.string()),
    ]
)

LINKBASES_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("form", pa.string()),
        ("linkbase_type", pa.string()),
        ("document_type", pa.string()),
        ("filename", pa.string()),
        ("url", pa.string()),
    ]
)

PAYLOAD_SCHEMA = pa.schema(
    [
        ("target_id", pa.string()),
        ("accession", pa.string()),
        ("outcome", pa.string()),
        ("attempt_count", pa.int32()),
        ("duration_ms", pa.int64()),
        ("body_sha256", pa.string()),
        ("body_byte_size", pa.int64()),
        ("body_storage_path", pa.string()),
    ]
)

JOINED_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("primary_document", pa.string()),
        ("outcome", pa.string()),
        ("body_byte_size", pa.int64()),
        ("body_storage_path", pa.string()),
        ("target_url", pa.string()),
    ]
)

SECTIONS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("form", pa.string()),
        ("item_identifier", pa.string()),
        ("canonical_name", pa.string()),
        ("heading", pa.string()),
        ("start_line", pa.int32()),
        ("end_line", pa.int32()),
        ("is_omitted", pa.bool_()),
        ("payload_sha256", pa.string()),
        ("renderer_version", pa.string()),
    ]
)

NOTES_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("form", pa.string()),
        ("note_number", pa.int32()),
        ("note_label", pa.string()),
        ("heading", pa.string()),
        ("start_line", pa.int32()),
        ("end_line", pa.int32()),
        ("payload_sha256", pa.string()),
        ("renderer_version", pa.string()),
    ]
)


def build_catalog_table(filings: Iterable[FilingAggregate]) -> pa.Table:
    """Build Arrow catalog table from filing aggregates."""
    batches: list[pa.RecordBatch] = []
    chunk: list[dict[str, Any]] = []

    for f in filings:
        primary_doc = f.primary_document_path or (
            f.primary_document_url.split("/")[-1] if f.primary_document_url else ""
        )
        chunk.append(
            {
                "accession": f.accession.value,
                "form": f.form,
                "filing_date": f.filing_date,
                "report_date": f.report_date or "",
                "primary_document": primary_doc,
                "primary_doc_url": f.primary_document_url or "",
            }
        )
        if len(chunk) >= DEFAULT_READ_BATCH_SIZE:
            batches.append(pa.RecordBatch.from_pylist(chunk, schema=CATALOG_SCHEMA))
            chunk.clear()

    if chunk:
        batches.append(pa.RecordBatch.from_pylist(chunk, schema=CATALOG_SCHEMA))

    if not batches:
        return pa.Table.from_batches([], schema=CATALOG_SCHEMA)
    return pa.Table.from_batches(batches, schema=CATALOG_SCHEMA)


def build_index_table(filings: Iterable[FilingAggregate]) -> pa.Table:
    """Build Arrow index/attachments table from filing aggregates."""
    batches: list[pa.RecordBatch] = []
    chunk: list[dict[str, Any]] = []

    for f in filings:
        atts = f.get_attachments()
        for idx, a in enumerate(atts, 1):
            seq_val = idx
            try:
                if a.attachment_id and a.attachment_id.isdigit():
                    seq_val = int(a.attachment_id)
            except Exception:
                pass
            chunk.append(
                {
                    "accession": f.accession.value,
                    "sequence": seq_val,
                    "document_type": a.document_type,
                    "filename": a.filename,
                    "description": a.description or "",
                    "size": a.size or 0,
                    "url": a.url,
                    "is_exhibit": is_exhibit_attachment(a.document_type, a.filename),
                }
            )
            if len(chunk) >= DEFAULT_READ_BATCH_SIZE:
                batches.append(pa.RecordBatch.from_pylist(chunk, schema=INDEX_SCHEMA))
                chunk.clear()

    if chunk:
        batches.append(pa.RecordBatch.from_pylist(chunk, schema=INDEX_SCHEMA))

    if not batches:
        return pa.Table.from_batches([], schema=INDEX_SCHEMA)
    return pa.Table.from_batches(batches, schema=INDEX_SCHEMA)


def build_exhibits_table(
    filings: Iterable[FilingAggregate], types: Sequence[str] | str = ()
) -> pa.Table:
    """Build Arrow exhibits table from filing aggregates."""
    filter_types = (
        {types.upper()}
        if isinstance(types, str) and types
        else {t.upper() for t in types}
        if types
        else None
    )
    batches: list[pa.RecordBatch] = []
    chunk: list[dict[str, Any]] = []

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
            chunk.append(
                {
                    "accession": f.accession.value,
                    "form": f.form,
                    "document_type": dt,
                    "description": ex.description or "",
                    "filename": ex.filename,
                    "size": ex.size or 0,
                    "url": ex.url,
                }
            )
            if len(chunk) >= DEFAULT_READ_BATCH_SIZE:
                batches.append(
                    pa.RecordBatch.from_pylist(chunk, schema=EXHIBITS_SCHEMA)
                )
                chunk.clear()

    if chunk:
        batches.append(pa.RecordBatch.from_pylist(chunk, schema=EXHIBITS_SCHEMA))

    if not batches:
        return pa.Table.from_batches([], schema=EXHIBITS_SCHEMA)
    return pa.Table.from_batches(batches, schema=EXHIBITS_SCHEMA)


def build_linkbases_table(filings: Iterable[FilingAggregate]) -> pa.Table:
    """Build Arrow linkbases table from filing aggregates."""
    batches: list[pa.RecordBatch] = []
    chunk: list[dict[str, Any]] = []

    for f in filings:
        for lb in f.linkbases:
            lb_type = classify_linkbase(
                lb.document_type or "",
                lb.filename or "",
                lb.description or "",
            )
            chunk.append(
                {
                    "accession": f.accession.value,
                    "form": f.form,
                    "linkbase_type": lb_type.value if lb_type is not None else "",
                    "document_type": lb.document_type,
                    "filename": lb.filename,
                    "url": lb.url,
                }
            )
            if len(chunk) >= DEFAULT_READ_BATCH_SIZE:
                batches.append(
                    pa.RecordBatch.from_pylist(chunk, schema=LINKBASES_SCHEMA)
                )
                chunk.clear()

    if chunk:
        batches.append(pa.RecordBatch.from_pylist(chunk, schema=LINKBASES_SCHEMA))

    if not batches:
        return pa.Table.from_batches([], schema=LINKBASES_SCHEMA)
    return pa.Table.from_batches(batches, schema=LINKBASES_SCHEMA)


def build_payload_table(filings: Iterable[FilingAggregate]) -> pa.Table:
    """Build Arrow payload/staged table from filing aggregates."""
    batches: list[pa.RecordBatch] = []
    chunk: list[dict[str, Any]] = []

    for idx, f in enumerate(filings, 1):
        has_body = (
            f.primary_storage_path is not None and f.primary_storage_path.is_file()
        ) or f.fetcher is not None
        b_size = 0
        if f.primary_storage_path and f.primary_storage_path.is_file():
            try:
                b_size = f.primary_storage_path.stat().st_size
            except OSError:
                b_size = 0
        chunk.append(
            {
                "target_id": f"tgt_{idx:03d}",
                "accession": f.accession.value,
                "outcome": "acquired" if has_body else "planned",
                "attempt_count": 1,
                "duration_ms": 0,
                "body_sha256": f.primary_sha256 or "",
                "body_byte_size": b_size,
                "body_storage_path": str(f.primary_storage_path)
                if f.primary_storage_path
                else "",
            }
        )
        if len(chunk) >= DEFAULT_READ_BATCH_SIZE:
            batches.append(pa.RecordBatch.from_pylist(chunk, schema=PAYLOAD_SCHEMA))
            chunk.clear()

    if chunk:
        batches.append(pa.RecordBatch.from_pylist(chunk, schema=PAYLOAD_SCHEMA))

    if not batches:
        return pa.Table.from_batches([], schema=PAYLOAD_SCHEMA)
    return pa.Table.from_batches(batches, schema=PAYLOAD_SCHEMA)


def build_joined_table(filings: Iterable[FilingAggregate]) -> pa.Table:
    """Build consolidated Arrow joined table from filing aggregates."""
    batches: list[pa.RecordBatch] = []
    chunk: list[dict[str, Any]] = []

    for f in filings:
        pdoc = f.primary_document_path or (
            f.primary_document_url.split("/")[-1] if f.primary_document_url else ""
        )
        has_body = (
            f.primary_storage_path is not None and f.primary_storage_path.is_file()
        ) or f.fetcher is not None
        b_size = None
        if f.primary_storage_path and f.primary_storage_path.is_file():
            try:
                b_size = f.primary_storage_path.stat().st_size
            except OSError:
                pass
        chunk.append(
            {
                "accession": f.accession.value,
                "form": f.form,
                "filing_date": f.filing_date,
                "primary_document": pdoc,
                "outcome": "acquired" if has_body else "planned",
                "body_byte_size": b_size,
                "body_storage_path": str(f.primary_storage_path)
                if f.primary_storage_path
                else None,
                "target_url": f.primary_document_url or "",
            }
        )
        if len(chunk) >= DEFAULT_READ_BATCH_SIZE:
            batches.append(pa.RecordBatch.from_pylist(chunk, schema=JOINED_SCHEMA))
            chunk.clear()

    if chunk:
        batches.append(pa.RecordBatch.from_pylist(chunk, schema=JOINED_SCHEMA))

    if not batches:
        return pa.Table.from_batches([], schema=JOINED_SCHEMA)
    return pa.Table.from_batches(batches, schema=JOINED_SCHEMA)


def build_sections_table(filings: Iterable[FilingAggregate]) -> pa.Table:
    """Build Arrow sections table from filing aggregates for covered forms."""
    from edgar_sec.domain.forms.common.aliases import resolve_alias
    from edgar_sec.domain.forms.families.processing_profiles import (
        get_family_entry,
    )
    from edgar_sec.domain.forms.reports import CompanyReport
    from edgar_sec.engine.forms.sections.items.detector import (
        detect_section_sequence,
    )

    batches: list[pa.RecordBatch] = []
    chunk: list[dict[str, Any]] = []

    for f in filings:
        if not f.has_sections:
            continue
        report = f.as_report()
        if not isinstance(report, CompanyReport):
            continue
        body = report.text()
        if not body:
            continue

        family = resolve_alias(f.form) or f.form.strip().upper()
        entry = get_family_entry(family)
        taxonomy = entry.taxonomy_items if entry is not None else ()
        if not taxonomy:
            continue

        toc_span = None
        if entry and entry.profile.has_toc:
            from edgar_sec.engine.forms.cover.toc.finder import find_toc_span

            toc_info = find_toc_span(body)
            if toc_info is not None:
                toc_span = (toc_info.start_line, toc_info.end_line)

        seq = detect_section_sequence(
            body,
            family=family,
            taxonomy_items=taxonomy,
            toc_span=toc_span,
            renderer_version=entry.profile.version if entry else "1",
        )
        for s in seq.sections:
            chunk.append(
                {
                    "accession": f.accession.value,
                    "form": f.form,
                    "item_identifier": s.item_identifier,
                    "canonical_name": s.title,
                    "heading": s.raw_heading,
                    "start_line": s.start_line,
                    "end_line": s.end_line or s.start_line,
                    "is_omitted": s.is_omitted,
                    "payload_sha256": seq.payload_sha256 or "",
                    "renderer_version": seq.renderer_version or "",
                }
            )
            if len(chunk) >= DEFAULT_READ_BATCH_SIZE:
                batches.append(
                    pa.RecordBatch.from_pylist(chunk, schema=SECTIONS_SCHEMA)
                )
                chunk.clear()

    if chunk:
        batches.append(pa.RecordBatch.from_pylist(chunk, schema=SECTIONS_SCHEMA))

    if not batches:
        return pa.Table.from_batches([], schema=SECTIONS_SCHEMA)
    return pa.Table.from_batches(batches, schema=SECTIONS_SCHEMA)


def build_notes_table(filings: Iterable[FilingAggregate]) -> pa.Table:
    """Build Arrow notes table from filing aggregates for covered forms."""
    from edgar_sec.domain.forms.families.processing_profiles import (
        get_family_profile,
    )
    from edgar_sec.domain.forms.reports import CompanyReport
    from edgar_sec.engine.forms.sections.notes.detector import (
        detect_notes_sequence,
    )

    batches: list[pa.RecordBatch] = []
    chunk: list[dict[str, Any]] = []

    for f in filings:
        if not f.has_notes:
            continue
        report = f.as_report()
        if not isinstance(report, CompanyReport):
            continue
        body = report.text()
        if not body:
            continue

        prof = get_family_profile(f.form)
        seq = detect_notes_sequence(
            body,
            renderer_version=prof.version if prof else "1",
        )
        for n in seq.notes:
            chunk.append(
                {
                    "accession": f.accession.value,
                    "form": f.form,
                    "note_number": n.note_number,
                    "note_label": n.note_label,
                    "heading": n.raw_heading,
                    "start_line": n.start_line,
                    "end_line": n.end_line or n.start_line,
                    "payload_sha256": seq.payload_sha256 or "",
                    "renderer_version": seq.renderer_version or "",
                }
            )
            if len(chunk) >= DEFAULT_READ_BATCH_SIZE:
                batches.append(pa.RecordBatch.from_pylist(chunk, schema=NOTES_SCHEMA))
                chunk.clear()

    if chunk:
        batches.append(pa.RecordBatch.from_pylist(chunk, schema=NOTES_SCHEMA))

    if not batches:
        return pa.Table.from_batches([], schema=NOTES_SCHEMA)
    return pa.Table.from_batches(batches, schema=NOTES_SCHEMA)


__all__ = [
    "build_catalog_table",
    "build_exhibits_table",
    "build_index_table",
    "build_joined_table",
    "build_linkbases_table",
    "build_notes_table",
    "build_payload_table",
    "build_sections_table",
    "is_exhibit_attachment",
]
