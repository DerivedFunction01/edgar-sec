"""Command surface for document inventory fixture and review operations."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.foundation.runtime.settings.validators import positive_int_type
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.broker.daemon import managed_broker
from edgar_sec.pipelines.document_inventory.cohort import (
    project_cohort,
    read_catalog_observations,
)
from edgar_sec.pipelines.document_inventory.discovery import (
    discover_fixtures,
    discover_plans,
)
from edgar_sec.pipelines.document_inventory.fixture_store.capture import (
    capture_index_pages,
    create_index_fixture,
)
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    FixtureContribution,
)
from edgar_sec.pipelines.document_inventory.paths import (
    InventoryPaths,
    resolve_filing_catalog_paths,
    resolve_index_fixture_paths,
)
from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME

_ARCHIVE_BASE_URL = "https://www.sec.gov/Archives/edgar/data"


def _artifacts_root(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return resolve_paths().artifacts_root.resolve()


def _plan(root: Path, plan_id: str) -> tuple[dict, dict, Path]:
    catalog_paths = resolve_filing_catalog_paths(root)
    plan = next(
        (item for item in discover_plans(root) if item["plan_id"] == plan_id), None
    )
    if plan is None:
        raise ValueError(f"catalog plan is not published: {plan_id}")
    plan_file = catalog_paths.plan_dir(plan_id) / PLAN_FILE_NAME
    try:
        metadata = json.loads(plan_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"catalog plan is unreadable: {plan_id}") from exc
    if not isinstance(metadata, dict):
        raise ValueError(f"catalog plan is malformed: {plan_id}")
    return plan, metadata, plan_file


def _cohort_for_plan(root: Path, plan_id: str, limit: int | None):
    plan, metadata, plan_file = _plan(root, plan_id)
    observations = list(
        read_catalog_observations(
            resolve_filing_catalog_paths(root).plan_dir(plan_id),
            f"plan:{plan_id}",
            "catalog_plan",
        )
    )
    cohort = project_cohort(observations, archive_base_url=_ARCHIVE_BASE_URL)
    if limit is not None and len(cohort.work_items) > limit:
        selected = cohort.work_items[:limit]
        selected_accessions = {str(item.accession) for item in selected}
        cohort = replace(
            cohort,
            observations=tuple(
                item
                for item in cohort.observations
                if str(item.accession) in selected_accessions
            ),
            accessions=tuple(
                item
                for item in cohort.accessions
                if str(item.accession) in selected_accessions
            ),
            sources=tuple(
                item
                for item in cohort.sources
                if str(item.accession) in selected_accessions
            ),
            work_items=selected,
        )
    fingerprint = sha256_text(
        canonical_json(
            {
                "catalog_id": plan.get("catalog_id"),
                "limit": limit,
                "plan_file_sha256": file_sha256(plan_file),
                "plan_id": plan_id,
                "selected_accessions": len(cohort.work_items),
                "scope": plan.get("scope"),
            }
        )
    )
    contribution = FixtureContribution(
        plan_id=plan_id,
        catalog_id=str(plan.get("catalog_id") or ""),
        scope=str(plan.get("scope") or "unknown"),
        plan_schema_version=str(metadata.get("schema_version") or "unknown"),
        request_fingerprint=fingerprint,
        accession_count=len(cohort.work_items),
    )
    return plan, cohort, contribution


def _emit(command: str, result: dict, json_output: bool) -> None:
    if json_output:
        print(
            json.dumps(
                {"schema_version": 1, "command": command, **result},
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        return
    for key, value in result.items():
        if key == "failures":
            continue
        print(f"{key.replace('_', ' ')}: {value}")
    for failure in result.get("failures", []):
        print(
            f"failed {failure['accession']}: {failure['failure_code']}"
            + (f" ({failure['error']})" if failure.get("error") else ""),
            file=sys.stderr,
        )


def _capture(args: argparse.Namespace, *, create: bool) -> int:
    root = _artifacts_root(args.artifacts)
    fixture_paths = resolve_index_fixture_paths(root, args.fixture)
    if create and (
        fixture_paths.manifest_path.exists() or fixture_paths.storage_path.exists()
    ):
        raise ValueError(f"fixture already exists: {args.fixture}")
    if not create and not (
        fixture_paths.manifest_path.is_file() and fixture_paths.storage_path.is_file()
    ):
        raise ValueError(f"fixture does not exist: {args.fixture}")

    plan, cohort, contribution = _cohort_for_plan(root, args.catalog_plan, args.limit)
    if create:
        create_index_fixture(fixture_paths, fixture_id=args.fixture)
    socket_id = f"fixture-{uuid4().hex}"
    broker_path = InventoryPaths(root).broker_socket_path(socket_id)
    with managed_broker(broker_path) as broker:
        capture = capture_index_pages(
            cohort,
            fixture_id=args.fixture,
            paths=fixture_paths,
            broker=broker,
            contribution=contribution,
        )
    result = {
        "fixture_id": args.fixture,
        "plan_id": args.catalog_plan,
        "catalog_id": plan.get("catalog_id"),
        "scope": plan.get("scope"),
        "requested_accessions": len(cohort.work_items),
        "responses_added": capture.responses_added,
        "responses_reused": capture.responses_reused,
        "cases_created": capture.cases_created,
        "members_created": capture.members_created,
        "failures": [
            {
                "accession": str(item.accession),
                "failure_code": item.failure_code,
                "error": item.raw_broker_error,
            }
            for item in capture.failures
        ],
    }
    _emit("fixture create" if create else "fixture fill", result, args.json)
    return 1 if capture.failures else 0


def cmd_fixture_create(args: argparse.Namespace) -> int:
    return _capture(args, create=True)


def cmd_fixture_fill(args: argparse.Namespace) -> int:
    return _capture(args, create=False)


def cmd_fixture_list(args: argparse.Namespace) -> int:
    root = _artifacts_root(args.artifacts)
    fixtures = discover_fixtures(root)
    result = {"fixtures": fixtures, "fixture_count": len(fixtures)}
    _emit("fixture list", result, args.json)
    if not args.json and not fixtures:
        print("no fixtures found under the selected artifacts root")
    return 0


def cmd_review_artifacts(args: argparse.Namespace) -> int:
    from edgar_sec.pipelines.document_inventory.review_artifacts.builder import (
        build_review_artifacts,
    )

    root = _artifacts_root(args.artifacts)
    fixture = resolve_index_fixture_paths(root, args.fixture)
    result = build_review_artifacts(
        fixture,
        Path(args.output).expanduser().resolve(),
        accessions=args.accession,
        limit=args.limit,
        workers=args.workers,
    )
    summary = result.summary
    payload = {
        "review_id": result.review_id,
        "fixture_id": args.fixture,
        "output": str(result.output_root),
        "total": summary.total,
        "parsed": summary.parsed,
        "unrecognized": summary.unrecognized,
        "parse_failures": summary.parse_failure,
        "execution_errors": summary.execution_error,
        "entries_total": summary.entries_total,
        "failed": summary.failed,
    }
    _emit("review-artifacts", payload, args.json)
    return result.exit_code


def cmd_build(args: argparse.Namespace) -> int:
    from edgar_sec.pipelines.document_inventory.snapshot.builder import build_inventory

    root = _artifacts_root(args.artifacts)
    publication = build_inventory(
        args.catalog_plan,
        base_snapshot_id=args.base_snapshot,
        explicit_refresh=args.explicit_refresh,
        chunk_size=args.chunk_size,
        retry_failures=args.retry_failures,
        workers=args.workers,
        artifacts_root=root,
    )
    payload = {
        "status": publication.status,
        "snapshot_id": (
            publication.snapshot.snapshot_id if publication.snapshot else None
        ),
        "reason": publication.reason,
    }
    _emit("inventory build", payload, args.json)
    return 0 if not publication.was_failed else 1


def cmd_query(args: argparse.Namespace) -> int:
    from edgar_sec.pipelines.document_inventory.snapshot.reader import (
        get_accessions_by_cik,
        get_accessions_by_source_cik,
        get_active_accession,
        get_active_entries,
        query_accessions,
    )

    root = _artifacts_root(args.artifacts)
    snapshots_root = InventoryPaths(root).snapshots_root

    results: list[dict[str, Any]] = []
    if args.accession:
        acc = get_active_accession(snapshots_root, args.accession)
        if acc:
            entries = get_active_entries(snapshots_root, args.accession)
            acc_copy = dict(acc)
            acc_copy["entries"] = entries
            results.append(acc_copy)
    elif args.filing_cik and not (args.form or args.source_cik):
        results = get_accessions_by_cik(snapshots_root, args.filing_cik)
    elif args.source_cik and not (args.form or args.filing_cik):
        results = get_accessions_by_source_cik(snapshots_root, args.source_cik)
    else:
        results = query_accessions(
            snapshots_root,
            form=args.form,
            filing_cik=args.filing_cik,
            source_cik=args.source_cik,
            limit=args.limit,
        )

    payload = {
        "count": len(results),
        "results": results,
    }
    _emit("inventory query", payload, args.json)
    return 0


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifacts", help="artifacts root override")
    parser.add_argument("--json", action="store_true", help="emit JSON to stdout")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inventory",
        description="Capture and review SEC filing index pages.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build_cmd = commands.add_parser(
        "build", help="build and publish an immutable inventory snapshot"
    )
    build_cmd.add_argument("--catalog-plan", required=True, help="published plan id")
    build_cmd.add_argument("--base-snapshot", help="base snapshot id override")
    build_cmd.add_argument(
        "--explicit-refresh",
        action="store_true",
        help="force re-fetch of index pages",
    )
    build_cmd.add_argument(
        "--chunk-size", type=positive_int_type, help="accessions per S4 chunk"
    )
    build_cmd.add_argument(
        "--retry-failures",
        action="store_true",
        help="retry failed chunk attempts",
    )
    build_cmd.add_argument(
        "--workers", type=positive_int_type, help="worker process count"
    )
    _add_output_options(build_cmd)
    build_cmd.set_defaults(func=cmd_build)

    query_cmd = commands.add_parser(
        "query", help="query active document inventory snapshots"
    )
    query_cmd.add_argument("--accession", help="exact accession number")
    query_cmd.add_argument("--form", help="filing form filter")
    query_cmd.add_argument("--filing-cik", help="canonical filing CIK filter")
    query_cmd.add_argument("--source-cik", help="discovery source CIK filter")
    query_cmd.add_argument("--limit", type=positive_int_type, help="limit results")
    _add_output_options(query_cmd)
    query_cmd.set_defaults(func=cmd_query)

    fixture = commands.add_parser(
        "fixture", help="create, fill, or list local fixtures"
    )
    fixture_commands = fixture.add_subparsers(dest="fixture_command", required=True)
    for name, handler, help_text in (
        ("create", cmd_fixture_create, "create and capture a fixture"),
        ("fill", cmd_fixture_fill, "extend an existing fixture"),
    ):
        child = fixture_commands.add_parser(name, help=help_text)
        child.add_argument("--fixture", required=True, help="fixture id")
        child.add_argument("--catalog-plan", required=True, help="published plan id")
        child.add_argument(
            "--limit", type=positive_int_type, help="limit captured accessions"
        )
        _add_output_options(child)
        child.set_defaults(func=handler)
    listing = fixture_commands.add_parser(
        "list", help="list manifest-discovered fixtures"
    )
    _add_output_options(listing)
    listing.set_defaults(func=cmd_fixture_list)

    review = commands.add_parser(
        "review-artifacts", help="review captured pages offline"
    )
    review.add_argument("--fixture", required=True, help="fixture id")
    review.add_argument("--output", required=True, help="new or empty review directory")
    review.add_argument(
        "--accession", action="append", help="limit to an accession; repeatable"
    )
    review.add_argument(
        "--limit", type=positive_int_type, help="limit selected captured pages"
    )
    review.add_argument(
        "--workers", type=positive_int_type, help="worker process count"
    )
    _add_output_options(review)
    review.set_defaults(func=cmd_review_artifacts)

    from edgar_sec.infra.storage.dag.cli import (
        attach_dag_subparser,
        dispatch_dag_subcommand,
    )
    from edgar_sec.pipelines.document_inventory.snapshot.specs import (
        INVENTORY_RELATIONS,
    )

    dag_parser = attach_dag_subparser(
        commands,
        subcommand_name="dag",
        default_root=lambda: InventoryPaths(_artifacts_root(None)).snapshots_root,
        default_specs=INVENTORY_RELATIONS,
    )
    dag_parser.set_defaults(
        func=lambda args: dispatch_dag_subcommand(
            args,
            default_root=lambda: (
                InventoryPaths(
                    _artifacts_root(getattr(args, "artifacts", None))
                ).snapshots_root
            ),
            default_specs=INVENTORY_RELATIONS,
        )
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None and len(sys.argv) == 1:
        build_parser().print_help()
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
