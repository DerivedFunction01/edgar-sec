#!/usr/bin/env python3
"""Decompress and dump documents from a Phase 2.5 published partition SQLite.

    PYTHONPATH=. .venv/bin/python phases/025_webpage_storage/tools/dump_documents.py \
        --db .artifacts/fixtures/diverse_10k_benchmark/fixture.sqlite \
        --out .artifacts/test-runs/filing_documents/dump-00001 \
        --limit 20

Each document is written to ``<out>/<doc_id>/<document_path>`` with a small
``.meta.json`` sidecar recording accession, form, byte_size, and mime_type.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import zstandard

from defs.sql import (
    Parameter,
    Select,
    SqlDialect,
    Table,
    col,
    make_sql_executor,
)
from defs.sql.predicates import Membership, ValueList
from defs.storage import atomic_write_json

NORMALIZED_DOCUMENTS_TABLE = "normalized_documents"

_DOC_COLUMNS = (
    "normalized_artifact_id",
    "source_doc_id",
    "byte_size",
    "mime_type",
    "normalized_payload",
    "payload_sha256",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="partition database path")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--limit", type=int, default=20, help="max documents to dump")
    parser.add_argument(
        "--doc-id",
        action="append",
        default=[],
        help="restrict to specific source_doc_ids",
    )
    parser.add_argument("--no-decompress", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dctx = zstandard.ZstdDecompressor()

    where = []
    if args.doc_id:
        where.append(
            Membership(
                col("source_doc_id"),
                source=ValueList(values=tuple(Parameter(p) for p in args.doc_id)),
            )
        )

    executor = make_sql_executor(args.db, dialect=SqlDialect.SQLITE)
    try:
        compiled = executor.compiler.compile(
            Select(
                source=Table(NORMALIZED_DOCUMENTS_TABLE),
                projection=tuple(col(c) for c in _DOC_COLUMNS),
                where=where[0] if len(where) == 1 else None,
                limit=args.limit,
            )
        )
        rows = executor.query(compiled)
    finally:
        executor.close()

    dumped = 0
    for row in rows:
        doc_id = row["source_doc_id"]
        artifact_id = row["normalized_artifact_id"]
        byte_size = row["byte_size"]
        mime_type = row["mime_type"]
        payload = row["normalized_payload"]

        doc_dir = out / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        target = doc_dir / f"{artifact_id}.md"

        if args.no_decompress:
            target.write_bytes(payload)
        else:
            try:
                raw = dctx.decompress(payload)
            except Exception as exc:  # noqa: BLE001
                print(f"WARN decompress failed for {doc_id}: {exc}", file=sys.stderr)
                raw = payload
            target.write_bytes(raw)

        meta = {
            "source_doc_id": doc_id,
            "artifact_id": artifact_id,
            "byte_size": byte_size,
            "mime_type": mime_type,
            "compressed_size": len(payload),
            "decompressed_size": len(target.read_bytes()),
            "path": str(target),
        }
        atomic_write_json(doc_dir / ".meta.json", meta, indent=2, sort_keys=True)
        dumped += 1
        if args.verbose:
            print(
                f"{doc_id} {artifact_id} "
                f"{len(payload)} -> {meta['decompressed_size']} bytes"
            )

    print(f"Dumped {dumped} documents to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
