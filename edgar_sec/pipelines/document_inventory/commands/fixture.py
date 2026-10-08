"""Index fixture creation, filling, and listing commands."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from uuid import uuid4

from edgar_sec.foundation.runtime.render import (
    Grid,
    KeyValueRow,
    ProseRow,
    render_output,
)
from edgar_sec.infra.broker.daemon import managed_broker
from edgar_sec.pipelines.document_inventory.discovery import discover_fixtures
from edgar_sec.pipelines.document_inventory.fixture_store.capture import (
    capture_index_pages,
    create_index_fixture,
)
from edgar_sec.pipelines.document_inventory.paths import (
    InventoryPaths,
    resolve_index_fixture_paths,
)

from .common import cohort_for_plan, resolve_artifacts_root


def _capture(args: argparse.Namespace, *, create: bool) -> int:
    """Capture index pages into a new or existing fixture."""
    root = resolve_artifacts_root(
        getattr(args, "artifacts_root", None) or getattr(args, "artifacts", None)
    )
    fixture_paths = resolve_index_fixture_paths(root, args.fixture)
    if create and (
        fixture_paths.manifest_path.exists() or fixture_paths.storage_path.exists()
    ):
        raise ValueError(f"fixture already exists: {args.fixture}")
    if not create and not (
        fixture_paths.manifest_path.is_file() and fixture_paths.storage_path.is_file()
    ):
        raise ValueError(f"fixture does not exist: {args.fixture}")

    plan, cohort, contribution = cohort_for_plan(root, args.catalog_plan, args.limit)

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

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "command": "fixture create" if create else "fixture fill",
                    **result,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    else:
        render_output(
            [
                KeyValueRow("fixture_id", str(args.fixture)),
                KeyValueRow("plan_id", str(args.catalog_plan)),
                KeyValueRow("catalog_id", str(plan.get("catalog_id") or "")),
                KeyValueRow("scope", str(plan.get("scope") or "")),
                KeyValueRow("requested_accessions", str(len(cohort.work_items))),
                KeyValueRow("responses_added", str(capture.responses_added)),
                KeyValueRow("responses_reused", str(capture.responses_reused)),
                KeyValueRow("cases_created", str(capture.cases_created)),
                KeyValueRow("members_created", str(capture.members_created)),
            ],
            title=f"Fixture {'Created' if create else 'Filled'} ({args.fixture})",
        )

    for failure in result.get("failures", []):
        err_msg = f" ({failure['error']})" if failure.get("error") else ""
        print(
            f"failed {failure['accession']}: {failure['failure_code']}{err_msg}",
            file=sys.stderr,
        )

    return 1 if capture.failures else 0


def cmd_fixture_create(args: argparse.Namespace) -> int:
    """Create a new index fixture from a catalog plan."""
    return _capture(args, create=True)


def cmd_fixture_fill(args: argparse.Namespace) -> int:
    """Extend an existing index fixture from a catalog plan."""
    return _capture(args, create=False)


def cmd_fixture_list(args: argparse.Namespace) -> int:
    """List discovered index fixtures."""
    root = resolve_artifacts_root(
        getattr(args, "artifacts_root", None) or getattr(args, "artifacts", None)
    )
    fixtures = discover_fixtures(root)
    result = {"fixtures": fixtures, "fixture_count": len(fixtures)}

    if getattr(args, "json", False):
        print(
            json.dumps(
                {"schema_version": 1, "command": "fixture list", **result},
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    else:
        if not fixtures:
            render_output(
                [ProseRow("no fixtures found under the selected artifacts root")],
                title="Fixtures",
            )
        else:
            headers = ("fixture_id", "capture_state", "pages", "accessions")
            rows = tuple(
                (
                    str(f.get("fixture_id", "")),
                    str(f.get("capture_state", "")),
                    str(f.get("page_count", 0)),
                    str(f.get("accession_count", 0)),
                )
                for f in fixtures
            )
            render_output(
                [
                    Grid(headers, rows),
                    KeyValueRow("fixture_count", str(len(fixtures))),
                ],
                title="Discovered Fixtures",
            )

    return 0
