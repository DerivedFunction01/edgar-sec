"""Per-filing successor extraction: normalize under the annotate policy
and assemble the context record kept per geometry.

Contexts are produced by the engine's one context-production function
(refresh Step 2); this module owns the record envelope, the label
join, defect notes, and exhibit resolution through the engine/forms
resolver. Location is found inside production by ordered sequential
search; a geometry that cannot be located is an issue on its record,
never a silent drop.
"""

from __future__ import annotations

import time
from dataclasses import replace

from edgar_sec.engine.document.page_markers.models import PageArtifactPolicy
from edgar_sec.engine.forms.exhibit_resolution import (
    ExhibitCandidateInput,
    resolve_exhibits,
)
from edgar_sec.engine.forms.normalize import NormalizationResult, normalize_document
from edgar_sec.engine.tables.extraction.context_production import (
    DocumentInput,
    produce_contexts,
)


def extract_filing(
    spec: dict,
    raw: bytes,
    document_path: str,
    *,
    tree: str,
    exhibits: tuple[dict, ...] = (),
    stratum: str | None = None,
) -> tuple[dict, list[dict], dict]:
    """Build one successor fixture record from primary bytes.

    Returns the record, filing-level defect entries as plain dicts, and
    the normalize/extract timing split. Fetch timing is the caller's.
    ``exhibits`` carries inventory dicts (document_type, document_name,
    raw); resolution runs only when ``stratum`` names the registry
    stratum the run measures, and only body-confirmed exhibits are
    produced, stamped with their source document.
    """
    accession = str(spec["accession"])
    record: dict = {
        "accession": accession,
        "cik": spec["cik"],
        "form": spec["form"],
        "filing_date": spec["filing_date"],
        "era": spec["era"],
        "is_xbrl": spec["is_xbrl"],
        "filer_category": spec.get("filer_category"),
        "population": "retained-409",
        "status": "ok",
        "error": None,
        "builder": {
            "tool": "tools/table_extraction_corpus",
            "policy": "annotate",
            "tree": tree,
            "primary_document": spec.get("primary_document"),
            "primary_source": spec.get("primary_source"),
        },
        "geometries": [],
    }
    entries: list[dict] = []

    def note(defect_class: str, explanation: str, **kwargs) -> None:
        entry = {
            "class": defect_class,
            "stage": "extract",
            "accession": accession,
            "table_index": kwargs.get("table_index"),
            "count": 1,
            "specimens": [kwargs["specimen"]] if kwargs.get("specimen") else [],
            "explanation": explanation,
        }
        entries.append(entry)

    started = time.perf_counter()
    result: NormalizationResult = normalize_document(
        raw,
        form=str(spec["form"]),
        document_path=document_path,
        page_policy=PageArtifactPolicy.ANNOTATE,
    )
    normalize_s = time.perf_counter() - started
    extract_started = time.perf_counter()

    exhibit_results: dict[str, NormalizationResult] = {}
    for exhibit in exhibits:
        exhibit_results[exhibit["document_name"]] = normalize_document(
            exhibit["raw"],
            form=str(spec["form"]),
            document_path=exhibit["document_name"],
            page_policy=PageArtifactPolicy.ANNOTATE,
        )
    resolved = ()
    if exhibits and stratum is not None:
        inventory = tuple(
            ExhibitCandidateInput(
                document_type=exhibit.get("document_type"),
                document_name=exhibit["document_name"],
                body_text=exhibit_results[exhibit["document_name"]].text,
            )
            for exhibit in exhibits
        )
        resolved = resolve_exhibits(
            inventory,
            stratum=stratum,
            filing_form=str(spec["form"]),
            primary_text=result.text,
        )
    documents = [DocumentInput("primary", result)]
    documents.extend(
        DocumentInput(entry.document_name, exhibit_results[entry.document_name])
        for entry in resolved
        if entry.body_confirmed
    )
    production = produce_contexts(tuple(documents))

    # Overlap rule (Step 5): a delegating primary is a stub, so its
    # exhibit is the sole source and nothing is dropped; otherwise an
    # exhibit geometry duplicating a primary geometry is dropped, so
    # a complete primary is never double-counted.
    delegation_by_name = {
        entry.document_name: entry.delegation for entry in resolved
    }

    def signature(geometry_record: dict) -> tuple:
        return tuple(
            tuple(" ".join(str(cell).split()).casefold() for cell in row)
            for row in geometry_record["rows"]
        )

    primary_signatures = {
        signature(dict(geometry_record))
        for document in production.documents
        if document.source_document == "primary"
        for geometry_record in document.records
    }
    overlap_dropped: dict[str, int] = {}
    geometry_counts: dict[str, int] = {}
    kept_documents = []
    for document in production.documents:
        if document.source_document == "primary":
            kept_documents.append(document)
            continue
        delegation = delegation_by_name.get(document.source_document)
        if delegation is not None and delegation.is_stub:
            kept = document.records
        else:
            kept = tuple(
                geometry_record
                for geometry_record in document.records
                if signature(dict(geometry_record)) not in primary_signatures
            )
        overlap_dropped[document.source_document] = len(document.records) - len(kept)
        geometry_counts[document.source_document] = len(kept)
        kept_documents.append(
            replace(document, records=kept)
            if len(kept) != len(document.records)
            else document
        )
    production = replace(production, documents=tuple(kept_documents))

    record["exhibits"] = [
        {
            "document_name": entry.document_name,
            "document_type": entry.document_type,
            "code": entry.code,
            "families": list(entry.families),
            "body_disposition": entry.body_disposition,
            "body_confirmed": entry.body_confirmed,
            "geometry_count": geometry_counts.get(entry.document_name, 0),
            "overlap_dropped": overlap_dropped.get(entry.document_name, 0),
            "delegation": (
                {
                    "is_stub": entry.delegation.is_stub,
                    "exhibit_index_only": entry.delegation.exhibit_index_only,
                    "anchors": entry.delegation.anchors,
                    "verbs": list(entry.delegation.verbs),
                }
                if entry.delegation is not None
                else None
            ),
        }
        for entry in resolved
    ]

    labels = {lab["table_index"]: lab for lab in spec.get("labels", [])}
    geometries: list[dict] = []
    for document in production.documents:
        if document.unresolved_breaks:
            note(
                "break-namespace-unresolved",
                "the line alignment between the annotated text and the "
                "page analysis source could not attribute every token to a "
                "marker span; unattributed break namespaces are recorded "
                "as null",
                specimen=(
                    f"tokens={document.token_count} "
                    f"unresolved={document.unresolved_breaks}"
                ),
            )
        specimens = dict(document.not_located_specimens)
        for geometry_record in document.records:
            geometry_record = dict(geometry_record)
            table_index = geometry_record["table_index"]
            if table_index in specimens:
                note(
                    "geometry-not-located",
                    "the geometry's rendered lines were not found in the "
                    "annotated text frame by ordered sequential search",
                    table_index=table_index,
                    specimen=specimens[table_index],
                )
            if document.source_document == "primary":
                label = labels.get(table_index)
                if label is None:
                    geometry_record["issues"] = [
                        *geometry_record["issues"],
                        "label-missing",
                    ]
                    note(
                        "label-missing",
                        "no retained-corpus label exists for this table_index",
                        table_index=table_index,
                    )
                geometry_record["label"] = label
            else:
                geometry_record["label"] = None
            geometries.append(geometry_record)
    record["geometries"] = geometries
    record["facts"] = production.documents[0].facts.as_record()
    timing = {
        "normalize_s": round(normalize_s, 4),
        "extract_s": round(time.perf_counter() - extract_started, 4),
    }
    return record, entries, timing
