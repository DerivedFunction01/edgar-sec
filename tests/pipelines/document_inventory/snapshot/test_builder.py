"""Offline unit tests for production inventory snapshot builder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.sec_http.metrics import HttpMetrics
from edgar_sec.pipelines.document_inventory.snapshot.builder import build_inventory
from edgar_sec.pipelines.document_inventory.snapshot.reader import (
    get_accessions_by_cik,
    get_accessions_by_source_cik,
    get_active_accession,
    get_active_entries,
)
from edgar_sec.pipelines.document_inventory.cohort import CohortInputError
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
    """Offline test double serving canned HTML while recording calls."""

    def __init__(self, failing: set[str] | None = None, fail_all: bool = False) -> None:
        self.failing = failing or set()
        self.fail_all = fail_all
        self.calls: list[str] = []
        self.metrics = HttpMetrics()

    def peek_cache(self, url: str) -> bytes | None:
        return None

    def get_bytes(self, url: str, *, force_refresh: bool = False) -> bytes:
        self.calls.append(url)
        if self.fail_all or url in self.failing:
            raise RuntimeError(f"synthetic HTTP error for {url}")
        return INDEX_HTML


def _build_plan(
    artifacts_root: Path,
    plan_id: str,
    table: pa.Table,
) -> Path:
    catalog_paths = FilingCatalogPaths(artifacts_root)
    root = catalog_paths.plan_dir(plan_id)
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
    return root


def test_validation_guard(tmp_path: Path, resource_profile) -> None:
    """Verify builder executes zero HTTP requests when plan validation fails."""
    http = _RecordingFakeHttp()
    with pytest.raises(CohortInputError, match="unpublished catalog plan"):
        build_inventory(
            "nonexistent-plan",
            http_client=http,
            artifacts_root=tmp_path,
            profile=resource_profile,
            workers=1,
        )
    assert len(http.calls) == 0


def test_publish_and_noop(tmp_path: Path, resource_profile) -> None:
    """Verify base snapshot publication advances current pointer and re-run is no-op."""
    table = pq.read_table(_OBSERVATIONS)
    plan_id = "plan-base"
    _build_plan(tmp_path, plan_id, table)
    http = _RecordingFakeHttp()

    pub = build_inventory(
        plan_id,
        http_client=http,
        artifacts_root=tmp_path,
        profile=resource_profile,
        workers=1,
    )
    assert pub.status == "published"
    assert pub.snapshot is not None
    assert pub.snapshot.accession_count > 0
    base_snapshot_id = pub.snapshot.snapshot_id
    call_count_1 = len(http.calls)
    assert call_count_1 > 0

    acc_row = get_active_accession(tmp_path, "0000320193-23-000106")
    assert acc_row is not None
    assert acc_row["form"] == "10-K"

    entries = get_active_entries(tmp_path, "0000320193-23-000106")
    assert len(entries) > 0

    ciks = get_accessions_by_cik(tmp_path, "0000320193")
    assert len(ciks) > 0

    sources = get_accessions_by_source_cik(tmp_path, "0000320193")
    assert len(sources) > 0

    # Idempotent re-run
    pub2 = build_inventory(
        plan_id,
        base_snapshot_id=base_snapshot_id,
        http_client=http,
        artifacts_root=tmp_path,
        profile=resource_profile,
        workers=1,
    )
    assert pub2.status == "no_op"
    assert len(http.calls) == call_count_1


def test_new_source_edges(tmp_path: Path, resource_profile) -> None:
    """Verify adding new source edges merges delta relations with zero HTTP calls."""
    table = pq.read_table(_OBSERVATIONS)
    plan_1 = "plan-1"
    _build_plan(tmp_path, plan_1, table)
    http = _RecordingFakeHttp()

    pub1 = build_inventory(
        plan_1,
        http_client=http,
        artifacts_root=tmp_path,
        profile=resource_profile,
        workers=1,
    )
    assert pub1.status == "published"
    assert pub1.snapshot is not None
    initial_calls = len(http.calls)

    # Build plan 2 with same accession but a new source CIK
    first_row = table.to_pylist()[0]
    extra_row = dict(first_row)
    extra_row["source_cik"] = "0000999999"
    extra_row["document_locator_key"] = "doc-new-source-edge"
    new_table = pa.Table.from_pylist([extra_row], schema=table.schema)
    plan_2 = "plan-2"
    _build_plan(tmp_path, plan_2, new_table)

    pub2 = build_inventory(
        plan_2,
        base_snapshot_id=pub1.snapshot.snapshot_id,
        http_client=http,
        artifacts_root=tmp_path,
        profile=resource_profile,
        workers=1,
    )
    assert pub2.status == "published"
    assert pub2.snapshot is not None
    assert len(http.calls) == initial_calls

    new_sources = get_accessions_by_source_cik(tmp_path, "0000999999")
    assert len(new_sources) == 1
    assert new_sources[0]["accession"] == "0000320193-23-000106"


def test_chunk_failure(tmp_path: Path, resource_profile) -> None:
    """Verify S4 chunk execution failure aborts publication and leaves current unchanged."""
    table = pq.read_table(_OBSERVATIONS)
    plan_id = "plan-fail"
    _build_plan(tmp_path, plan_id, table)

    http = _RecordingFakeHttp(fail_all=True)

    pub = build_inventory(
        plan_id,
        http_client=http,
        artifacts_root=tmp_path,
        profile=resource_profile,
        workers=1,
    )
    assert pub.status == "failed"
    assert "refused or failed" in (pub.reason or "")
    assert get_active_accession(tmp_path, "0000320193-23-000106") is None
