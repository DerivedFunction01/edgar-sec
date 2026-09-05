"""Build source-first review artifacts for selected Phase 025 documents."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from tqdm import tqdm

from defs.runtime.resources import default_cpu_cores
from defs.storage import atomic_write_text

from ..testing.corpus import find_document_cases
from ..testing.paths import fixture_paths, review_run_root
from ..testing.review import process_and_write_review_case
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
    extensions = list(args.extension) if args.extension else None
    if args.fixture_id:
        paths = fixture_paths(args.fixture_id)
        _load_fixture_manifest(paths)
        records = build_records(
            paths,
            ids=set(ids) or None,
            limit=args.limit,
            extensions=extensions,
        )
        return sorted(records, key=lambda record: str(record["document_id"]))
    selected = find_document_cases(
        ids=ids or None,
        categories=args.category or None,
        extensions=extensions,
        path=args.corpus,
    )
    return selected[: args.limit] if args.limit else selected


def _process_case_task(record: dict[str, Any], case_dir: Path) -> dict[str, Any]:
    return process_and_write_review_case(record, case_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture-id")
    source.add_argument("--corpus", type=Path)
    parser.add_argument("--id", action="append", dest="ids", default=[])
    parser.add_argument("--ids-file", type=Path)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument(
        "--extension",
        "--ext",
        action="append",
        default=[],
        help="filter by document extension (e.g. .txt, .htm, .html)",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=None,
        help="number of parallel worker processes (default: all available CPU cores up to 32)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="disable tqdm progress bar",
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:

        parser.error("--limit must be positive")
    if args.workers is not None and args.workers <= 0:
        parser.error("--workers must be positive")
    records = _records(args)
    if not records:
        parser.error("selection matched no documents")
    root = args.output or review_run_root()
    if args.output is not None and root.exists() and any(root.iterdir()):
        parser.error(f"review output already contains artifacts: {root}")
    cases_root = root / "cases"
    cases_root.mkdir(parents=True, exist_ok=True)

    max_workers = args.workers if args.workers is not None else default_cpu_cores()

    manifest_by_id: dict[str, dict[str, Any]] = {}

    if max_workers == 1 or len(records) == 1:
        with tqdm(
            records,
            desc="Building review artifacts",
            unit="docs",
            disable=args.no_progress,
        ) as pbar:
            for record in pbar:
                doc_id = str(record["document_id"])
                manifest_by_id[doc_id] = _process_case_task(record, cases_root / doc_id)
    else:
        pool = ProcessPoolExecutor(max_workers=max_workers)
        try:
            futures = {
                pool.submit(
                    _process_case_task,
                    record,
                    cases_root / str(record["document_id"]),
                ): str(record["document_id"])
                for record in records
            }
            with tqdm(
                total=len(records),
                desc="Building review artifacts",
                unit="docs",
                disable=args.no_progress,
            ) as pbar:
                for future in as_completed(futures):
                    doc_id = futures[future]
                    manifest_by_id[doc_id] = future.result()
                    pbar.update(1)
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)


    manifest = [manifest_by_id[str(record["document_id"])] for record in records]
    atomic_write_text(
        root / "review_manifest.jsonl",
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in manifest),
    )
    print(f"wrote {len(manifest)} document review artifacts to {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
