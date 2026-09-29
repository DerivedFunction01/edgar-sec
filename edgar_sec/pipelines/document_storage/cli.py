"""Command line for the document-storage pipeline.

Three subcommands, matching the three things a run does:

``run``      acquire, normalize, and publish a snapshot from a fixture
``status``   report what is currently published
``review``   render review bundles from a published snapshot (M6.1)

``run`` is offline by design: a corpus must be reproducible from a fixture before
a live acquisition is worth trusting. Live acquisition goes through the broker,
which owns pacing, so this CLI does not construct its own HTTP client.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.paths import ProjectPaths, resolve_paths
from edgar_sec.pipelines.document_storage.merger import (
    current_snapshot_artifact,
    current_snapshot_dir,
    read_pointer,
)

USAGE_EPILOG = """\
examples:
  python run.py documents status
  python run.py documents run --plan corpus.json --fixture fix-001
  python run.py documents review --limit 20
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="documents",
        description="Document storage: acquire, normalize, snapshot, review.",
        epilog=USAGE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="acquire and publish a snapshot from a fixture")
    run.add_argument("--plan", required=True, help="path to a chunk plan JSON file")
    run.add_argument("--fixture", required=True, help="fixture id to replay from")
    run.add_argument("--run-id", default=None, help="run identity; generated if absent")
    run.add_argument("--workers", type=int, default=None, help="explicit worker count")
    run.add_argument(
        "--limit", type=int, default=None, help="cap chunks for a smoke run"
    )
    run.add_argument("--json", action="store_true", help="emit the report as JSON")

    status = sub.add_parser("status", help="report the published snapshot")
    status.add_argument("--json", action="store_true", help="emit JSON")

    review = sub.add_parser("review", help="render review bundles from a snapshot")
    review.add_argument("--limit", type=int, default=None, help="max bundles to render")
    review.add_argument("--run-id", default=None, help="run to render under")
    review.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def _load_plan(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"plan not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _plan_to_inputs(
    plan: dict[str, Any], limit: int | None
) -> tuple[list[str], dict[str, list], dict[str, list]]:
    """Turn a plan file into the chunk tables the worker consumes.

    Returns ``(chunk_ids, locators_by_chunk, occurrences_by_chunk)``. Missing
    per-chunk locators are an empty chunk rather than an error, so a plan may
    declare more chunks than a smoke run wants.
    """
    from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence

    chunks = plan.get("chunks") or []
    if limit is not None and limit > 0:
        chunks = chunks[:limit]

    chunk_ids: list[str] = []
    locators_by_chunk: dict[str, list] = {}
    occurrences_by_chunk: dict[str, list] = {}
    for index, chunk in enumerate(chunks):
        chunk_id = str(chunk.get("chunk_id") or f"c{index:05d}")
        locators: list[DocumentLocator] = []
        for entry in chunk.get("locators", []):
            locators.append(
                DocumentLocator.from_parts(
                    str(entry["accession"]),
                    str(entry["document_path"]),
                    archive_url=entry.get("archive_url"),
                    form=entry.get("form"),
                    source_cik=entry.get("source_cik"),
                )
            )
        occurrences: list[FilingOccurrence] = []
        for row in chunk.get("occurrences", []):
            occurrences.append(FilingOccurrence.from_row(dict(row)))
        chunk_ids.append(chunk_id)
        locators_by_chunk[chunk_id] = locators
        occurrences_by_chunk[chunk_id] = occurrences
    return chunk_ids, locators_by_chunk, occurrences_by_chunk


def _cmd_run(args: argparse.Namespace, paths: ProjectPaths) -> int:
    from edgar_sec.pipelines.document_storage.operator import (
        new_run_id,
        run_document_storage,
    )

    plan = _load_plan(Path(args.plan))
    chunk_ids, locators_by_chunk, occurrences_by_chunk = _plan_to_inputs(
        plan, args.limit
    )
    if not chunk_ids:
        print("plan contains no chunks", file=sys.stderr)
        return 1

    report = run_document_storage(
        paths=paths,
        run_id=args.run_id or new_run_id(),
        chunk_ids=chunk_ids,
        locators_by_chunk=locators_by_chunk,
        occurrences_by_chunk=occurrences_by_chunk,
        mode="fixture",
        fixture_id=args.fixture,
        workers=args.workers,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"run           {report.run_id}")
        print(f"snapshot      {report.snapshot_id}")
        print(f"artifact      {report.artifact_path}")
        print(f"rows          {report.merge.snapshot.row_count}")
        print(f"chunks        {report.merge.snapshot.chunk_count}")
        print(f"documents     {report.total_documents}")
        print(f"failed        {report.failed_documents}")
        print(f"exhibits      {len(report.exhibits)}")
        for warning in report.merge.warnings:
            print(f"warning       {warning}")
    return 0 if report.ok else 1


def _cmd_status(args: argparse.Namespace, paths: ProjectPaths) -> int:
    pointer = read_pointer(paths.documents_root)
    directory = current_snapshot_dir(paths.documents_root)
    artifact = current_snapshot_artifact(paths.documents_root)
    payload = {
        "pointer": pointer,
        "artifact": str(artifact) if artifact else None,
        "shape": "run" if artifact else "consolidated",
        "published": directory is not None,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif payload["published"]:
        assert pointer is not None
        assert directory is not None
        print(f"snapshot      {pointer.get('snapshot_id')}")
        print(f"run           {pointer.get('run_id')}")
        print(f"shape         {payload['shape']}")
        if artifact is not None:
            print(f"artifact      {artifact}")
        print(f"pointed_at    {pointer.get('pointed_at')}")
    else:
        print("no snapshot is published")
    return 0 if payload["published"] else 1


def _cmd_review(args: argparse.Namespace, paths: ProjectPaths) -> int:
    from edgar_sec.pipelines.document_storage.review import render_review_set

    directory = current_snapshot_dir(paths.documents_root)
    if directory is None:
        print("no snapshot is published; run 'documents run' first", file=sys.stderr)
        return 1
    # A run snapshot reads from its assembled artifact; a consolidated one from
    # its part tree. Both are passed as a path the review harness recognizes.
    source = current_snapshot_artifact(paths.documents_root) or directory
    run_id = (
        args.run_id
        or (read_pointer(paths.documents_root) or {}).get("run_id")
        or "latest"
    )
    result = render_review_set(
        artifact_path=source,
        output_dir=paths.review_dir(str(run_id)),
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"run           {run_id}")
        print(f"bundles       {result.rendered}")
        print(f"skipped       {result.skipped}")
        print(f"output        {result.output_dir}")
        for item in result.errors:
            print(f"error         {item}")
    return 0 if not result.errors else 1


_COMMANDS = {"run": _cmd_run, "status": _cmd_status, "review": _cmd_review}


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``python run.py documents ...``."""
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    paths = resolve_paths()
    handler = _COMMANDS[args.command]
    try:
        return handler(args, paths)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main"]
