"""Command line and interactive operator for document storage.

``run`` is offline by design: a corpus must be reproducible from a fixture before a
live acquisition is worth trusting. Live acquisition goes through the broker.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.pipelines.document_storage.paths import DocumentStoragePaths
from edgar_sec.pipelines.document_storage.merger import (
    current_snapshot_artifact,
    current_snapshot_dir,
    read_pointer,
)

USAGE_EPILOG = """\
examples:
  python run.py documents status
  python run.py documents run --plan corpus.json --fixture fix-001
  python run.py documents review-artifacts --fixture fix-001 --limit 100
  python run.py documents review --base <run-a> --new <run-b>
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
    _add_plan_input(run)
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

    review = sub.add_parser(
        "review", help="compare two review runs and report what changed"
    )
    review.add_argument("--base", required=True, help="earlier review run directory")
    review.add_argument("--new", required=True, help="later review run directory")
    review.add_argument(
        "--output", default=None, help="diff output directory; must be empty"
    )
    review.add_argument("--json", action="store_true", help="emit JSON")

    artifacts = sub.add_parser(
        "review-artifacts",
        help="render source-first review artifacts from a fixture",
    )
    artifacts.add_argument("--fixture", required=True, help="fixture id to review")
    artifacts.add_argument("--limit", type=int, default=None, help="max documents")
    artifacts.add_argument(
        "--id",
        action="append",
        dest="ids",
        default=[],
        help="document id or document-path suffix; repeatable",
    )
    artifacts.add_argument(
        "--ids-file", type=Path, default=None, help="file of ids, one per line"
    )
    artifacts.add_argument(
        "--extension",
        "--ext",
        action="append",
        default=[],
        help="restrict to a document extension, e.g. htm; repeatable",
    )
    artifacts.add_argument(
        "--run-id", default=None, help="run identity; generated if absent"
    )
    artifacts.add_argument(
        "--output", type=Path, default=None, help="output directory; must not exist"
    )
    artifacts.add_argument("--workers", type=int, default=None, help="worker processes")
    artifacts.add_argument(
        "--json", action="store_true", help="emit the report as JSON"
    )

    fill = sub.add_parser("fill", help="fetch missing raw payloads into a fixture")
    _add_plan_input(fill)
    fill.add_argument("--fixture", required=True, help="fixture id to create or extend")
    fill.add_argument("--workers", type=int, default=None, help="fetch worker count")
    fill.add_argument("--limit", type=int, default=None, help="cap target locators")
    fill.add_argument("--json", action="store_true", help="emit the report as JSON")

    fixtures = sub.add_parser("fixtures", help="list available fixture stores")
    fixtures.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def _add_plan_input(parser: argparse.ArgumentParser) -> None:
    """Attach the two mutually exclusive plan inputs.

    ``--plan`` is a hand-authored JSON plan; ``--catalog-plan`` is a published catalog
    bundle that is validated and streamed. Separate modes, not one option with two meanings.
    """
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", help="path to a hand-authored chunk plan JSON file")
    group.add_argument(
        "--catalog-plan",
        dest="catalog_plan",
        help="path to a published filing_catalog plan bundle directory",
    )


def _load_plan(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"plan not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _open_catalog_plan(path: str) -> Any:
    """Validate a published catalog bundle and resolve its chunk size."""
    from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
    from edgar_sec.pipelines.document_storage.catalog_plan import CatalogPlan

    return CatalogPlan(path, chunk_size=resolve_runtime_settings().default_chunk_size)


def _plan_to_inputs(
    plan: dict[str, Any], limit: int | None
) -> tuple[list[str], dict[str, list], dict[str, list]]:
    """Turn a plan file into ``(chunk_ids, locators_by_chunk, occurrences_by_chunk)``.

    Missing per-chunk locators are an empty chunk, not an error, so a plan may declare
    more chunks than a smoke run wants.
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


def _cmd_run(args: argparse.Namespace, paths: DocumentStoragePaths) -> int:
    from edgar_sec.pipelines.document_storage.operator import (
        new_run_id,
        run_document_storage,
    )

    work_order = None
    if getattr(args, "catalog_plan", None):
        work_order = _open_catalog_plan(args.catalog_plan)
        if args.limit is not None and args.limit > 0:
            print(
                "--limit applies to a JSON plan; a catalog plan is run whole",
                file=sys.stderr,
            )
            return 2
        report = run_document_storage(
            paths=paths,
            run_id=args.run_id or new_run_id(),
            work_order=work_order,
            catalog_plan=work_order,
            mode="fixture",
            fixture_id=args.fixture,
            workers=args.workers,
        )
        return _print_run_report(report, args.json)

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
    return _print_run_report(report, args.json)


def _print_run_report(report: Any, as_json: bool) -> int:
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"run           {report.run_id}")
        print(f"snapshot      {report.snapshot_id}")
        print(f"artifact      {report.artifact_path}")
        print(f"rows          {report.merge.snapshot.row_count}")
        print(f"chunks        {report.merge.snapshot.chunk_count}")
        print(f"documents     {report.total_documents}")
        print(f"failed        {report.failed_documents}")
        print(f"eligible      {report.candidate_eligible_count}")
        print(f"candidates    {report.bundle_candidate_count}")
        print(f"undated       {report.candidate_date_unresolved_count}")
        exhibit_count = (
            len(report.exhibits)
            if report.exhibits_resolved_count is None
            else report.exhibits_resolved_count
        )
        print(f"exhibits      {exhibit_count}")
        if report.run_status is not None:
            print(f"run state     {report.run_status}")
            print(f"fresh chunks  {report.fresh_chunk_count}")
            print(f"resumed chunks {report.resumed_chunk_count}")
            print(f"reused chunks {report.reused_chunk_count}")
        for warning in report.merge.warnings:
            print(f"warning       {warning}")
    return 0 if report.ok else 1


def _cmd_fill(args: argparse.Namespace, paths: DocumentStoragePaths) -> int:
    from edgar_sec.pipelines.document_storage.fixture_operator import fill_fixture

    if getattr(args, "catalog_plan", None):
        plan = _open_catalog_plan(args.catalog_plan)
        report = fill_fixture(
            paths=paths,
            fixture_id=args.fixture,
            locator_source=plan.iter_locators(),
            limit=args.limit,
            workers=args.workers,
            target_reference=plan.metadata.plan_id,
            target_fingerprint=plan.metadata.selection_fingerprint,
        )
        return _print_fill_report(report, args.json)

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
    return _print_fill_report(report, args.json)


def _print_fill_report(report: Any, as_json: bool) -> int:
    if as_json:
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


def _cmd_fixtures(args: argparse.Namespace, paths: DocumentStoragePaths) -> int:
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


def _cmd_status(args: argparse.Namespace, paths: DocumentStoragePaths) -> int:
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


def _ids_file(path: Path | None) -> list[str]:
    """Read selection tokens from a file, one per line, ``#`` comments allowed."""
    if path is None:
        return []
    if not path.is_file():
        raise FileNotFoundError(f"ids file not found: {path}")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _cmd_review_artifacts(args: argparse.Namespace, paths: DocumentStoragePaths) -> int:
    from edgar_sec.pipelines.document_storage.review_artifacts import (
        ReviewArtifactError,
        new_review_run_id,
        render_review_run,
    )

    if args.limit is not None and args.limit <= 0:
        print("--limit must be positive", file=sys.stderr)
        return 2
    if args.workers is not None and args.workers <= 0:
        print("--workers must be positive", file=sys.stderr)
        return 2
    ids = [*args.ids, *_ids_file(args.ids_file)]
    run_id = args.run_id or new_review_run_id()
    output = Path(args.output) if args.output else paths.review_run_dir(run_id)
    try:
        result = render_review_run(
            paths,
            args.fixture,
            output,
            ids=ids,
            extensions=args.extension,
            limit=args.limit,
            workers=args.workers,
        )
    except ReviewArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"fixture       {args.fixture}")
        print(f"selected      {result.selected}")
        print(f"rendered      {result.rendered}")
        print(f"output        {result.output_dir}")
        if result.forms_inferred:
            print(
                f"note          {result.forms_inferred} document(s) reviewed under a "
                "manifest-declared form, not a per-document one"
            )
        for failure in result.failures:
            print(f"error         {failure}")
    return 0 if not result.failures else 1


def _cmd_review(args: argparse.Namespace, paths: DocumentStoragePaths) -> int:
    from edgar_sec.pipelines.document_storage.review import (
        ReviewDiffError,
        compare_review_runs,
    )
    from edgar_sec.pipelines.document_storage.review_artifacts import new_review_run_id

    base = Path(args.base)
    new = Path(args.new)
    output = (
        Path(args.output)
        if args.output
        else paths.review_runs_root / f"diff-{new_review_run_id()}"
    )
    try:
        result = compare_review_runs(base, new, output)
    except ReviewDiffError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print((output / "summary.txt").read_text(encoding="utf-8"), end="")
    # Differences are a result, not a failure; a reviewer reads them.
    return 1 if result.has_changes else 0


_COMMANDS = {
    "run": _cmd_run,
    "status": _cmd_status,
    "review": _cmd_review,
    "review-artifacts": _cmd_review_artifacts,
    "fill": _cmd_fill,
    "fixtures": _cmd_fixtures,
}


def _interactive(paths: DocumentStoragePaths) -> int:
    """Present the narrow fixture lifecycle menu used by the root launcher."""
    from edgar_sec.pipelines.document_storage.fixture_operator import list_fixtures

    while True:
        print("\nDocument Storage (Phase 2.5)")
        print("  1. Fill or extend a fixture")
        print("  2. Run a plan from a fixture")
        print("  3. List fixtures")
        print("  4. Build review artifacts from a fixture")
        print("  5. Compare two review runs")
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
            if choice == "4":
                fixture_id = input("Fixture ID: ").strip()
                limit = input("Document limit (blank for all): ").strip()
                if fixture_id:
                    _cmd_review_artifacts(
                        argparse.Namespace(
                            fixture=fixture_id,
                            limit=int(limit) if limit else None,
                            ids=[],
                            ids_file=None,
                            extension=[],
                            run_id=None,
                            output=None,
                            workers=None,
                            json=False,
                        ),
                        paths,
                    )
                continue
            if choice == "5":
                base = input("Base review run: ").strip()
                new = input("New review run: ").strip()
                if base and new:
                    _cmd_review(
                        argparse.Namespace(base=base, new=new, output=None, json=False),
                        paths,
                    )
                continue
            if choice == "1":
                plan_path = input("Target plan JSON path: ").strip()
                fixture_id = input("Fixture ID: ").strip()
                if plan_path and fixture_id:
                    _cmd_fill(
                        argparse.Namespace(
                            plan=plan_path,
                            catalog_plan=None,
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
                            catalog_plan=None,
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
        return _interactive(DocumentStoragePaths.from_project(resolve_paths()))
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    paths = DocumentStoragePaths.from_project(resolve_paths())
    handler = _COMMANDS[args.command]
    try:
        return handler(args, paths)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main"]
