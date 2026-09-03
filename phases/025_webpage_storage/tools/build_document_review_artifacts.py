"""Build source-first review artifacts for selected Phase 025 documents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from defs.storage import atomic_write_text

from ..testing.corpus import find_document_cases
from ..testing.paths import fixture_paths, review_run_root
from ..testing.review import run_document_case, write_review_artifacts
from .promote_document_corpus import _load_fixture_manifest, build_records


def _ids_file(path: Path | None) -> list[str]:
    if path is None:
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _records(args: argparse.Namespace) -> list[dict[str, Any]]:
    ids = list(args.ids)
    ids.extend(_ids_file(args.ids_file))
    if args.fixture_id:
        paths = fixture_paths(args.fixture_id)
        _load_fixture_manifest(paths)
        records = build_records(paths, ids=set(ids) or None, limit=args.limit)
        return sorted(records, key=lambda record: str(record["document_id"]))
    selected = find_document_cases(
        ids=ids or None,
        categories=args.category or None,
        path=args.corpus,
    )
    return selected[: args.limit] if args.limit else selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture-id")
    source.add_argument("--corpus", type=Path)
    parser.add_argument("--id", action="append", dest="ids", default=[])
    parser.add_argument("--ids-file", type=Path)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    records = _records(args)
    if not records:
        parser.error("selection matched no documents")
    root = args.output or review_run_root()
    if args.output is not None and root.exists() and any(root.iterdir()):
        parser.error(f"review output already contains artifacts: {root}")
    cases_root = root / "cases"
    cases_root.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for record in records:
        result = run_document_case(record)
        manifest.append(
            write_review_artifacts(
                result,
                cases_root / result.document_id,
                expected_output=record.get("expected_output"),
                expected_metadata=record.get("expected_metadata"),
            )
        )
    atomic_write_text(
        root / "review_manifest.jsonl",
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in manifest),
    )
    print(f"wrote {len(manifest)} document review artifacts to {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
