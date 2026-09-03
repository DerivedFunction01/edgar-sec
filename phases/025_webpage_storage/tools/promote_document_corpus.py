"""Promote raw documents from a fixture ID into the tracked corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from defs.runtime.paths import FixturePaths
from defs.sql import (
    Membership,
    OrderBy,
    Parameter,
    Select,
    SqlDialect,
    Star,
    Table,
    ValueList,
    col,
    make_sql_executor,
)
from defs.storage import atomic_write_json, file_sha256, pa, write_table_atomic

from ..core.schemas import DOCUMENT_BLOBS_TABLE, decompress_payload
from ..testing.corpus import DOCUMENT_CORPUS_SCHEMA, load_document_corpus
from ..testing.paths import document_corpus_path, document_manifest_path, fixture_paths


def _load_fixture_manifest(paths: FixturePaths) -> dict[str, Any]:
    if not paths.db_path.is_file():
        raise FileNotFoundError(f"fixture database not found: {paths.db_path}")
    if not paths.manifest_path.is_file():
        raise FileNotFoundError(f"fixture manifest not found: {paths.manifest_path}")
    try:
        manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid fixture manifest: {paths.manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("fixture manifest must contain an object")
    if manifest.get("fixture_id") != paths.fixture_id:
        raise ValueError("fixture manifest belongs to a different fixture ID")
    if manifest.get("storage_format") != "sqlite":
        raise ValueError("document corpus promotion requires a SQLite fixture")
    return manifest


def _fixture_rows(paths: FixturePaths, ids: set[str] | None) -> list[dict[str, Any]]:
    executor = make_sql_executor(paths.db_path, dialect=SqlDialect.SQLITE)
    try:
        where = None
        if ids:
            where = Membership(
                col("doc_id"),
                source=ValueList(tuple(Parameter(value) for value in sorted(ids))),
            )
        statement = Select(
            source=Table(DOCUMENT_BLOBS_TABLE),
            projection=(Star(),),
            where=where,
            order_by=(OrderBy(col("doc_id")),),
        )
        return executor.query(executor.compiler.compile(statement))
    finally:
        executor.close()


def build_records(
    paths: FixturePaths,
    *,
    ids: set[str] | None = None,
    limit: int | None = None,
    existing: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Read, decompress, verify, and shape fixture blobs for Parquet."""

    rows = _fixture_rows(paths, ids)
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        rows = rows[:limit]
    records: list[dict[str, Any]] = []
    for row in rows:
        raw = decompress_payload(bytes(row["raw_payload"]))
        digest = hashlib.sha256(raw).hexdigest()
        source_hash = str(row["raw_payload_sha256"] or "")
        if len(source_hash) != 64:
            raise ValueError(f"missing source hash for {row['doc_id']}")
        if digest != source_hash:
            raise ValueError(f"source hash mismatch for {row['doc_id']}")
        document_id = str(row["doc_id"])
        previous = (existing or {}).get(document_id)
        if previous is not None and previous.get("source_sha256") != digest:
            raise ValueError(f"source changed for existing corpus row {document_id}")
        records.append(
            {
                "document_id": document_id,
                "accession": str(row["accession"]),
                "document_path": str(row["document_path"]),
                "mime_type": str(row["mime_type"]),
                "source_sha256": digest,
                "source_bytes": raw,
                "expected_output": previous.get("expected_output")
                if previous is not None
                else None,
                "expected_metadata": previous.get("expected_metadata")
                if previous is not None
                else None,
                "review_status": previous.get("review_status", "pending")
                if previous is not None
                else "pending",
                "review_notes": previous.get("review_notes")
                if previous is not None
                else None,
            }
        )
    return records


def promote(
    fixture_id: str,
    *,
    output: Path | None = None,
    version: str = "v1",
    ids: set[str] | None = None,
    limit: int | None = None,
) -> Path:
    paths = fixture_paths(fixture_id)
    fixture_manifest = _load_fixture_manifest(paths)
    target = output or document_corpus_path(version)
    existing = {}
    if target.is_file():
        existing = {
            str(record["document_id"]): record
            for record in load_document_corpus(target)
        }
    promoted = build_records(paths, ids=ids, limit=limit, existing=existing)
    records_by_id = dict(existing)
    records_by_id.update({str(record["document_id"]): record for record in promoted})
    records = [records_by_id[key] for key in sorted(records_by_id)]
    if not records:
        raise ValueError("fixture contains no document blobs matching the selection")
    table = pa.Table.from_pylist(records, schema=DOCUMENT_CORPUS_SCHEMA)
    write_table_atomic(
        table,
        target,
        expected_rows=len(records),
        expected_schema=DOCUMENT_CORPUS_SCHEMA,
    )
    manifest_target = (
        document_manifest_path(version)
        if output is None
        else target.parent / "manifest.json"
    )
    manifest = {
        "corpus_version": version,
        "corpus_path": str(target),
        "corpus_sha256": file_sha256(target),
        "fixture_id": fixture_id,
        "fixture_manifest_sha256": file_sha256(paths.manifest_path),
        "fixture_manifest_schema_version": fixture_manifest.get(
            "fixture_manifest_schema_version"
        ),
        "document_count": len(records),
        "accepted_count": sum(
            record["review_status"] in {"accepted", "accepted_current_behavior"}
            for record in records
        ),
        "pending_count": sum(
            record["review_status"] == "pending" for record in records
        ),
    }
    atomic_write_json(manifest_target, manifest)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--doc-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    target = promote(
        args.fixture_id,
        output=args.output,
        version=args.version,
        ids=set(args.doc_id) or None,
        limit=args.limit,
    )
    print(f"wrote document corpus to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
