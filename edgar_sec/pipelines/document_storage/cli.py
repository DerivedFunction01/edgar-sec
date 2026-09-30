"""Command line and interactive operator for document storage.

Three subcommands, matching the three things a run does:

``run``      acquire, normalize, and publish a snapshot from a fixture
``status``   report what is currently published
``review``   render review bundles from a published snapshot (M6.1)
``fill``     fetch missing raw payloads into a fixture
``fixtures`` list available fixture stores

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
    run.add_argument(
        "--fixture",
        required=True,
        action="append",
        help="fixture id to replay from; repeat to define lookup precedence",
    )
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

    fill = sub.add_parser("fill", help="fetch missing raw payloads into a fixture")
    fill.add_argument(
        "--plan", required=True, help="path to a v2 target plan JSON file"
    )
    fill.add_argument("--fixture", required=True, help="fixture id to create or extend")
    fill.add_argument("--workers", type=int, default=None, help="fetch worker count")
    fill.add_argument("--limit", type=int, default=None, help="cap target locators")
    fill.add_argument("--json", action="store_true", help="emit the report as JSON")

    fixtures = sub.add_parser("fixtures", help="list available fixture stores")
    fixtures.add_argument("--json", action="store_true", help="emit JSON")
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


def _cmd_fill(args: argparse.Namespace, paths: ProjectPaths) -> int:
    from edgar_sec.pipelines.document_storage.fixture_operator import fill_fixture

    plan = _load_plan(Path(args.plan))
    _chunk_ids, locators_by_chunk, _occurrences = _plan_to_inputs(plan, None)
    locators = [locator for chunk in locators_by_chunk.values() for locator in chunk]
    report = fill_fixture(
        paths=paths,
        fixture_id=args.fixture,
        locators=locators,
        limit=args.limit,
        workers=args.workers,
        target_reference=args.plan,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"fixture       {report.fixture_id}")
        print(f"requested     {report.requested}")
        print(f"already       {report.already_present}")
        print(f"new           {report.newly_written}")
        print(f"failed        {report.failed}")
        for failure in report.failures:
            print(f"error         {failure['doc_id']}: {failure['error']}")
    return 0 if report.failed == 0 else 1


def _cmd_fixtures(args: argparse.Namespace, paths: ProjectPaths) -> int:
    from edgar_sec.pipelines.document_storage.fixture_operator import list_fixtures

    fixtures = list_fixtures(paths)
    payload = [
        {
            "fixture_id": item.fixture_id,
            "payload_count": item.payload_count,
            "manifest_status": item.manifest_status,
        }
        for item in fixtures
    ]
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif not fixtures:
        print("no fixture stores found")
    else:
        for item in payload:
            print(
                f"{item['fixture_id']:<24} payloads={item['payload_count']} "
                f"manifest={item['manifest_status']}"
            )
    return 0


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


_COMMANDS = {
    "run": _cmd_run,
    "status": _cmd_status,
    "review": _cmd_review,
    "fill": _cmd_fill,
    "fixtures": _cmd_fixtures,
}


def _interactive(paths: ProjectPaths) -> int:
    """Present the narrow fixture lifecycle menu used by the root launcher."""
    from edgar_sec.pipelines.document_storage.fixture_operator import list_fixtures

    while True:
        print("\nDocument Storage (Phase 2.5)")
        print("  1. Fill or extend a fixture")
        print("  2. Run a plan from a fixture")
        print("  3. List fixtures")
        print("  0. Exit")
        try:
            choice = input("Choice [0]: ").strip()
        except EOFError:
            return 0
        if not choice or choice == "0":
            return 0
        try:
            if choice == "3":
                _cmd_fixtures(argparse.Namespace(json=False), paths)
                continue
            if choice == "1":
                plan_path = input("Target plan JSON path: ").strip()
                fixture_id = input("Fixture ID: ").strip()
                if plan_path and fixture_id:
                    _cmd_fill(
                        argparse.Namespace(
                            plan=plan_path,
                            fixture=fixture_id,
                            workers=None,
                            limit=None,
                            json=False,
                        ),
                        paths,
                    )
                continue
            if choice == "2":
                fixtures = list_fixtures(paths)
                if not fixtures:
                    print("no fixture stores found; fill one first")
                    continue
                for index, fixture in enumerate(fixtures, 1):
                    print(
                        f"  {index}. {fixture.fixture_id} "
                        f"({fixture.payload_count} payloads; manifest {fixture.manifest_status})"
                    )
                selected = input("Fixture number: ").strip()
                index = int(selected) - 1
                if index < 0 or index >= len(fixtures):
                    print("invalid fixture selection")
                    continue
                plan_path = input("Target plan JSON path: ").strip()
                if plan_path:
                    _cmd_run(
                        argparse.Namespace(
                            plan=plan_path,
                            fixture=[fixtures[index].fixture_id],
                            run_id=None,
                            workers=None,
                            limit=None,
                            json=False,
                        ),
                        paths,
                    )
                continue
            print("Invalid choice, please select again.")
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``python run.py documents ...``."""
    if argv is None and len(sys.argv) == 1:
        return _interactive(resolve_paths())
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
