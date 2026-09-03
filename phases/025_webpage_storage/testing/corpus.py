"""Typed loading and filtering for the tracked document corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from defs.storage import DatasetSpec, pa, read_records

from .paths import document_manifest_path, find_document_corpus

VALID_REVIEW_STATUSES = frozenset({"pending", "accepted", "accepted_current_behavior"})
EXPECTED_STATUSES = frozenset({"accepted", "accepted_current_behavior"})

DOCUMENT_CORPUS_SCHEMA = pa.schema(
    [
        ("document_id", pa.string()),
        ("accession", pa.string()),
        ("document_path", pa.string()),
        ("mime_type", pa.string()),
        ("source_sha256", pa.string()),
        ("source_bytes", pa.binary()),
        ("expected_output", pa.string()),
        ("expected_metadata", pa.string()),
        ("review_status", pa.string()),
        ("review_notes", pa.string()),
    ]
)
DOCUMENT_CORPUS_SPEC = DatasetSpec(
    name="document_corpus",
    schema_version="1",
    key_field="document_id",
    arrow_schema=DOCUMENT_CORPUS_SCHEMA,
    required_fields=tuple(DOCUMENT_CORPUS_SCHEMA.names),
)


def validate_review_records(records: list[dict[str, Any]]) -> None:
    """Validate review-state semantics after physical schema validation."""

    seen: set[str] = set()
    for record in records:
        document_id = str(record["document_id"])
        if document_id in seen:
            raise ValueError(f"duplicate document ID: {document_id}")
        seen.add(document_id)
        status = str(record.get("review_status") or "")
        if status not in VALID_REVIEW_STATUSES:
            raise ValueError(f"invalid review status for {document_id}: {status}")
        if status in EXPECTED_STATUSES:
            if record.get("expected_output") is None:
                raise ValueError(
                    f"accepted document has no expected output: {document_id}"
                )
            if record.get("expected_metadata") is None:
                raise ValueError(
                    f"accepted document has no expected metadata: {document_id}"
                )
            try:
                metadata = json.loads(str(record["expected_metadata"]))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid expected metadata for {document_id}"
                ) from exc
            if not isinstance(metadata, dict):
                raise ValueError(
                    f"expected metadata must be an object for {document_id}"
                )
            if status == "accepted_current_behavior" and not metadata.get("deferred"):
                raise ValueError(
                    f"accepted_current_behavior requires deferred features: {document_id}"
                )


def load_document_corpus(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load and validate the tracked corpus, defaulting through ``paths.py``."""

    corpus_path = Path(path) if path is not None else find_document_corpus()
    records = read_records(corpus_path, "parquet", spec=DOCUMENT_CORPUS_SPEC)
    validate_review_records(records)
    return records


def load_document_manifest(path: str | Path | None = None) -> dict[str, Any]:
    """Load the tracked corpus manifest."""

    manifest_path = Path(path) if path is not None else document_manifest_path()
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"cannot read document corpus manifest: {manifest_path}"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError("document corpus manifest must contain an object")
    return value


def _record_categories(record: dict[str, Any]) -> set[str]:
    categories: set[str] = set()
    path = str(record.get("document_path", "")).casefold()
    mime = str(record.get("mime_type", "")).casefold()
    if path.endswith(".txt") or mime == "text/plain":
        categories.add("native_ascii")
    if path.endswith((".htm", ".html", ".xhtml")) or mime == "text/html":
        categories.add("html_source")
    expected_metadata = record.get("expected_metadata")
    if expected_metadata:
        try:
            metadata = json.loads(expected_metadata)
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        for category in metadata.get("categories", ()):
            categories.add(str(category))
    return categories


def find_document_cases(
    ids: list[str] | None = None,
    categories: list[str] | None = None,
    *,
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic corpus rows filtered by ID and review category."""

    records = load_document_corpus(path)
    id_set = set(ids or ())
    category_set = {value.casefold() for value in categories or ()}
    selected = [
        record
        for record in records
        if (not id_set or record["document_id"] in id_set)
        and (
            not category_set
            or category_set.intersection(
                category.casefold() for category in _record_categories(record)
            )
        )
    ]
    return sorted(selected, key=lambda record: str(record["document_id"]))


__all__ = [
    "DOCUMENT_CORPUS_SCHEMA",
    "DOCUMENT_CORPUS_SPEC",
    "EXPECTED_STATUSES",
    "VALID_REVIEW_STATUSES",
    "find_document_cases",
    "load_document_corpus",
    "load_document_manifest",
    "validate_review_records",
]
