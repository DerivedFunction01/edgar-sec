"""Normalization of filing-history arrays, file descriptors, and accession deduplication."""

from __future__ import annotations

from typing import Any

from .helpers import (
    SEC_SUBMISSIONS_BASE,
    accession_normalized,
    add_anomaly,
    build_archive_url,
    canonical_json,
    to_bool,
    to_int,
)

FILING_ARRAY_KEYS = [
    "accessionNumber",
    "filingDate",
    "reportDate",
    "acceptanceDateTime",
    "act",
    "form",
    "fileNumber",
    "filmNumber",
    "items",
    "core_type",
    "size",
    "isXBRL",
    "isInlineXBRL",
    "isXBRLNumeric",
    "primaryDocument",
    "primaryDocDescription",
]


def normalize_items(value: Any) -> list[str]:
    """SEC provides items as a list of codes in recent history but some
    historical files use comma-joined strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value)]


def zip_filing_arrays(
    section: dict,
    source_section: str,
    source_file: str,
    anomalies: list[dict],
    cik_padded: str = "",
) -> list[dict]:
    """Zip one SEC filing-history column-oriented array set into record
    objects, one per index.

    Equal array lengths are validated first; on a mismatch the available
    values are emitted by index with null padding, a schema anomaly records
    the source array lengths, and no array is silently truncated.
    """
    lengths = {}
    for key in FILING_ARRAY_KEYS:
        value = section.get(key)
        lengths[key] = len(value) if isinstance(value, list) else 0
    distinct = set(lengths.values())
    mismatch = len(distinct) > 1

    unknown = [key for key in section if key not in FILING_ARRAY_KEYS]
    if unknown:
        add_anomaly(
            anomalies,
            "unknown_filing_array_keys",
            canonical_json(sorted(unknown)),
            source_section,
        )

    if mismatch:
        add_anomaly(
            anomalies,
            "filing_array_length_mismatch",
            canonical_json(lengths),
            source_section,
        )

    records: list[dict] = []
    row_count = max(lengths.values()) if lengths else 0
    for index in range(row_count):

        def pick(key: str, _index: int = index) -> Any:
            values = section.get(key)
            if not isinstance(values, list) or _index >= len(values):
                return None
            return values[_index]

        accession_raw = pick("accessionNumber")
        primary_document = pick("primaryDocument")
        archive_url, fallback_reason = build_archive_url(
            cik_padded, accession_raw, primary_document
        )
        record = {
            "accession_number": accession_raw,
            "accession_number_normalized": accession_normalized(accession_raw),
            "filing_date": pick("filingDate"),
            "report_date": pick("reportDate"),
            "acceptance_datetime": pick("acceptanceDateTime"),
            "act": pick("act"),
            "form": pick("form"),
            "file_number": pick("fileNumber"),
            "film_number": pick("filmNumber"),
            "items": normalize_items(pick("items")),
            "core_type": pick("core_type"),
            "size": to_int(pick("size")),
            "is_xbrl": to_bool(pick("isXBRL")),
            "is_inline_xbrl": to_bool(pick("isInlineXBRL")),
            "is_xbrl_numeric": to_bool(pick("isXBRLNumeric")),
            "primary_document": primary_document,
            "primary_doc_description": pick("primaryDocDescription"),
            "archive_url": archive_url,
            "source_section": source_section,
            "source_file": source_file,
            "source_array_index": index,
        }
        if fallback_reason:
            add_anomaly(
                anomalies,
                fallback_reason.split(":")[0],
                f"index {index}: {fallback_reason}",
                f"{source_section}#{accession_raw}",
            )
        if mismatch and record["accession_number_normalized"] is None:
            add_anomaly(
                anomalies,
                "accession_unusable",
                f"index {index}: accession {accession_raw!r} is not a valid SEC accession",
                source_section,
            )
        records.append(record)
    return records


def dedupe_filings(
    records: list[dict], anomalies: list[dict], source: str
) -> tuple[list[dict], int]:
    """Deduplicate by normalized accession and detect conflicting metadata
    rather than silently choosing an arbitrary row. First occurrence wins;
    duplicates with identical content are dropped quietly, conflicts are
    recorded. Returns (unique_records, duplicate_count)."""
    seen: dict[str, dict] = {}
    out: list[dict] = []
    duplicates = 0
    for record in records:
        key = record.get("accession_number_normalized")
        if key is None:
            out.append(record)  # unusable accessions are kept and flagged upstream
            continue
        existing = seen.get(key)
        if existing is None:
            seen[key] = record
            out.append(record)
            continue
        duplicates += 1
        comparable = ("form", "filing_date", "report_date", "primary_document")
        differing = {
            field: (existing.get(field), record.get(field))
            for field in comparable
            if existing.get(field) != record.get(field)
        }
        if differing:
            add_anomaly(
                anomalies,
                "accession_conflict",
                canonical_json(differing),
                f"{source}#{key}",
            )
    return out, duplicates


def normalize_submission_files(files: Any, anomalies: list[dict]) -> list[dict]:
    """Normalize the historical submissions-file descriptors, handling the
    case variants FilingCount/FilingFrom/FilingTo."""
    if files is None:
        return []
    if not isinstance(files, list):
        add_anomaly(anomalies, "files_not_list", type(files).__name__, "filings.files")
        return []
    aliases = {
        "name": ["name"],
        "filing_count": ["FilingCount", "filingCount"],
        "filing_from": ["FilingFrom", "filingFrom"],
        "filing_to": ["FilingTo", "filingTo"],
    }
    out = []
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            add_anomaly(
                anomalies,
                "file_descriptor_not_object",
                canonical_json(entry)[:200],
                f"filings.files[{index}]",
            )
            continue
        record = {}
        for field, keys in aliases.items():
            values = [entry[key] for key in keys if key in entry]
            if not values:
                record[field] = None
            else:
                record[field] = values[0]
                if any(v != values[0] for v in values):
                    add_anomaly(
                        anomalies,
                        "alias_conflict",
                        f"{field}: {canonical_json(values)}",
                        f"filings.files[{index}]",
                    )
        record["filing_count"] = to_int(record["filing_count"])
        record["url"] = (
            f"{SEC_SUBMISSIONS_BASE}/{record['name']}" if record["name"] else None
        )
        out.append(record)
    return out


__all__ = [
    "FILING_ARRAY_KEYS",
    "dedupe_filings",
    "normalize_items",
    "normalize_submission_files",
    "zip_filing_arrays",
]
