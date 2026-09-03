"""Promote explicitly reviewed current outputs into the document corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from defs.storage import pa, write_table_atomic

from ..testing.corpus import DOCUMENT_CORPUS_SCHEMA, load_document_corpus
from ..testing.paths import document_corpus_path
from ..testing.review import run_document_case, stable_expected_metadata


def _read_ids(path: Path | None, ids: list[str]) -> list[str]:
    values = list(ids)
    if path is not None:
        values.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return list(dict.fromkeys(values))


def promote(
    corpus_path: Path,
    ids: list[str],
    *,
    source_hashes: dict[str, str] | None = None,
    status: str = "accepted",
    deferred: list[str] | None = None,
) -> int:
    if status not in {"accepted", "accepted_current_behavior"}:
        raise ValueError(f"invalid expectation status: {status}")
    if status == "accepted_current_behavior" and not deferred:
        raise ValueError("accepted_current_behavior requires deferred features")
    records = load_document_corpus(corpus_path)
    by_id = {str(record["document_id"]): record for record in records}
    missing = sorted(set(ids) - by_id.keys())
    if missing:
        raise ValueError(f"unknown document ID(s): {', '.join(missing)}")
    for document_id in ids:
        record = by_id[document_id]
        actual_hash = hashlib.sha256(bytes(record["source_bytes"])).hexdigest()
        if actual_hash != record["source_sha256"]:
            raise ValueError(f"source hash mismatch for {document_id}")
        if (
            source_hashes
            and document_id in source_hashes
            and (actual_hash != source_hashes[document_id])
        ):
            raise ValueError(f"review source hash mismatch for {document_id}")
        result = run_document_case(record)
        record["expected_output"] = result.normalized_text
        metadata = stable_expected_metadata(result)
        if deferred:
            metadata["deferred"] = sorted(set(deferred))
        record["expected_metadata"] = json.dumps(
            metadata, sort_keys=True, separators=(",", ":")
        )
        record["review_status"] = status
    table = pa.Table.from_pylist(records, schema=DOCUMENT_CORPUS_SCHEMA)
    write_table_atomic(
        table,
        corpus_path,
        expected_rows=len(records),
        expected_schema=DOCUMENT_CORPUS_SCHEMA,
    )
    return len(ids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument("--id", action="append", default=[])
    parser.add_argument("--ids-file", type=Path)
    parser.add_argument(
        "--status",
        choices=("accepted", "accepted_current_behavior"),
        default="accepted",
    )
    parser.add_argument("--deferred", action="append", default=[])
    args = parser.parse_args(argv)
    ids = _read_ids(args.ids_file, args.id)
    if not ids:
        parser.error("one of --id or --ids-file is required")
    corpus = args.corpus or document_corpus_path()
    count = promote(corpus, ids, status=args.status, deferred=args.deferred)
    print(f"promoted {count} document expectations in {corpus}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
