from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.sec_http.metrics import HttpMetrics
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.publication import StaleParentError
from edgar_sec.pipelines.document_inventory.commands.run import cmd_run
from edgar_sec.pipelines.document_inventory.commands.publish import cmd_publish
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.run_state import load_run_status
from edgar_sec.pipelines.document_inventory.snapshot.projection import (
    project_catalog_plan,
)
from edgar_sec.pipelines.document_inventory.snapshot.reader import (
    get_accessions_by_source_cik,
    get_active_accession,
    get_active_entries,
)
from edgar_sec.pipelines.filing_catalog.paths import FilingCatalogPaths
from edgar_sec.pipelines.filing_catalog.publication import plan_fingerprint
from tests.support import fixture_path

INDEX_HTML = fixture_path("document_inventory_index_page.html").read_bytes()
_OBSERVATIONS = fixture_path("catalog") / "cohort_observations.parquet"


@pytest.fixture
def resource_profile(tmp_path: Path):
    return derive_resources(
        requested_threads=1,
        cli_overrides={"runtime.temp_directory": str(tmp_path / "duckdb-tmp")},
    )


class _RecordingFakeHttp:
    def __init__(self, *, fail_all: bool = False) -> None:
        self.fail_all = fail_all
        self.calls: list[str] = []
        self.metrics = HttpMetrics()

    def peek_cache(self, url: str) -> bytes | None:
        return None

    def get_bytes(self, url: str, *, force_refresh: bool = False) -> bytes:
        self.calls.append(url)
        if self.fail_all:
            raise RuntimeError(f"synthetic HTTP error for {url}")
        return INDEX_HTML


def _build_plan(artifacts_root: Path, plan_id: str, table: pa.Table) -> None:
    root = FilingCatalogPaths(artifacts_root).plan_dir(plan_id)
    root.mkdir(parents=True)
    (root / "selection_report.json").write_text("{}", encoding="utf-8")
    forms = sorted(set(table.column("form").to_pylist()))
    counts = {}
    for form in forms:
        rows = table.filter(pc.equal(table.column("form"), form))
        target = root / "targets" / f"form={form.replace('/', '_')}" / "data.parquet"
        target.parent.mkdir(parents=True)
        pq.write_table(rows, target)
        counts[form] = rows.num_rows
    locator_keys = sorted(set(table.column("document_locator_key").to_pylist()))
    pq.write_table(
        pa.table({"document_locator_key": pa.array(locator_keys, type=pa.string())}),
        root / "locator_groups.parquet",
    )
    payload = {
        "plan_id": plan_id,
        "plan_schema_version": "1.2",
        "catalog_id": "catalog-test",
        "scope": "deterministic",
        "forms": forms,
        "counts": counts,
        "selected_rows": sum(counts.values()),
        "active_targets_count": sum(counts.values()),
        "unique_locators_count": len(locator_keys),
    }
    payload["plan_fingerprint"] = plan_fingerprint(payload, locator_keys)
    (root / "plan.json").write_text(json.dumps(payload), encoding="utf-8")


def _run(root: Path, run_id: str, http, profile) -> int:
    return cmd_run(
        Namespace(
            artifacts_root=str(root),
            run_id=run_id,
            workers=1,
            retry_failures=False,
            confirm_stale_lock=False,
            json=False,
            http_client=http,
            profile=profile,
        )
    )


def _publish(root: Path, run_id: str, profile) -> int:
    return cmd_publish(
        Namespace(
            artifacts_root=str(root),
            run_id=run_id,
            branch="main",
            expected_branch_tip=None,
            json=False,
            profile=profile,
        )
    )


def test_project_run_publish_and_repeat_are_separate(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    _build_plan(tmp_path, "plan-base", table)
    projection = project_catalog_plan(
        "plan-base", artifacts_root=tmp_path, profile=resource_profile
    )
    http = _RecordingFakeHttp()

    assert _run(tmp_path, projection.run_id, http, resource_profile) == 0
    status = load_run_status(tmp_path, projection.run_id)
    assert status.state == "ready"
    assert status.committed_chunks == status.expected_chunks
    assert http.calls
    assert _publish(tmp_path, projection.run_id, resource_profile) == 0
    pointer = DAGCatalog(InventoryPaths(tmp_path).snapshots_root).read_pointer("main")
    assert pointer
    snapshots_root = InventoryPaths(tmp_path).snapshots_root
    before_status = {path.name for path in snapshots_root.iterdir()}
    assert load_run_status(tmp_path, projection.run_id).state == "published"
    assert {path.name for path in snapshots_root.iterdir()} == before_status

    assert get_active_accession(tmp_path, "0000320193-23-000106") is not None
    assert get_active_entries(tmp_path, "0000320193-23-000106")

    repeated = project_catalog_plan(
        "plan-base", artifacts_root=tmp_path, profile=resource_profile
    )
    assert repeated.work_order_rows == 0
    assert repeated.base_snapshot_id == pointer["snapshot_id"]
    assert _run(tmp_path, repeated.run_id, _RecordingFakeHttp(), resource_profile) == 0
    assert _publish(tmp_path, repeated.run_id, resource_profile) == 0
    assert load_run_status(tmp_path, repeated.run_id).state == "ready"


def test_failed_run_cannot_be_published(tmp_path: Path, resource_profile) -> None:
    _build_plan(tmp_path, "plan-fail", pq.read_table(_OBSERVATIONS))
    projection = project_catalog_plan(
        "plan-fail", artifacts_root=tmp_path, profile=resource_profile
    )

    assert (
        _run(
            tmp_path,
            projection.run_id,
            _RecordingFakeHttp(fail_all=True),
            resource_profile,
        )
        == 0
    )
    status = load_run_status(tmp_path, projection.run_id)
    assert status.state == "blocked"
    assert status.retryable_failures > 0
    with pytest.raises(ValueError, match="not publishable"):
        _publish(tmp_path, projection.run_id, resource_profile)
    assert (
        DAGCatalog(InventoryPaths(tmp_path).snapshots_root).read_pointer("main") is None
    )
    assert get_active_accession(tmp_path, "0000320193-23-000106") is None


def test_publish_refuses_branch_that_moved_after_projection(
    tmp_path: Path, resource_profile
) -> None:
    _build_plan(tmp_path, "plan-moving-branch", pq.read_table(_OBSERVATIONS))
    projection = project_catalog_plan(
        "plan-moving-branch", artifacts_root=tmp_path, profile=resource_profile
    )
    assert (
        _run(tmp_path, projection.run_id, _RecordingFakeHttp(), resource_profile) == 0
    )
    catalog = DAGCatalog(InventoryPaths(tmp_path).snapshots_root)
    catalog.write_pointer("main", "unexpected-tip")

    with pytest.raises(StaleParentError, match="pinned to"):
        _publish(tmp_path, projection.run_id, resource_profile)

    assert catalog.read_pointer("main")["snapshot_id"] == "unexpected-tip"


def test_zero_work_source_edge_is_published_without_http(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    _build_plan(tmp_path, "plan-first", table)
    first = project_catalog_plan(
        "plan-first", artifacts_root=tmp_path, profile=resource_profile
    )
    http = _RecordingFakeHttp()
    assert _run(tmp_path, first.run_id, http, resource_profile) == 0
    assert _publish(tmp_path, first.run_id, resource_profile) == 0
    initial_calls = len(http.calls)

    row = dict(table.to_pylist()[0])
    row["source_cik"] = "0000999999"
    _build_plan(
        tmp_path, "plan-source", pa.Table.from_pylist([row], schema=table.schema)
    )
    second = project_catalog_plan(
        "plan-source", artifacts_root=tmp_path, profile=resource_profile
    )
    assert second.work_order_rows == 0
    no_http = _RecordingFakeHttp()
    assert _run(tmp_path, second.run_id, no_http, resource_profile) == 0
    assert no_http.calls == []
    assert _publish(tmp_path, second.run_id, resource_profile) == 0
    assert len(http.calls) == initial_calls
    source_rows = get_accessions_by_source_cik(tmp_path, "0000999999")
    assert [row["accession"] for row in source_rows] == ["0000320193-23-000106"]
