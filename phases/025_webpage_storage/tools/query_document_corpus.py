"""Inspect or search the tracked Phase 025 document corpus."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from ..testing.corpus import load_document_corpus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--id")
    parser.add_argument("--grep")
    parser.add_argument("--status")
    parser.add_argument("--show", choices=("source", "expected"), default="expected")
    parser.add_argument("--head", type=int)
    args = parser.parse_args(argv)
    if not args.id and not args.grep and not args.status:
        parser.error("one of --id, --grep, or --status is required")
    records = load_document_corpus(args.corpus)
    pattern = re.compile(args.grep, re.IGNORECASE) if args.grep else None
    selected = []
    for record in records:
        if args.id and record["document_id"] != args.id:
            continue
        if args.status and record["review_status"] != args.status:
            continue
        source = bytes(record["source_bytes"]).decode("utf-8", errors="replace")
        expected = record.get("expected_output") or ""
        if pattern and not pattern.search(source) and not pattern.search(expected):
            continue
        selected.append(record)
    for index, record in enumerate(selected):
        if index:
            print("\n" + "=" * 100)
        print(f"ID: {record['document_id']}")
        print(f"Accession: {record['accession']}")
        print(f"Document: {record['document_path']}")
        print(f"Status: {record['review_status']}")
        text = (
            bytes(record["source_bytes"]).decode("utf-8", errors="replace")
            if args.show == "source"
            else record.get("expected_output") or "(no expected output)"
        )
        if args.head is not None:
            text = "\n".join(text.splitlines()[: args.head])
        print(text)
    return 0 if selected else 1


if __name__ == "__main__":
    raise SystemExit(main())
