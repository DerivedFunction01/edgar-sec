from __future__ import annotations

import json
import os
import resource
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.filing_catalog.schemas import TARGET_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.pipelines.document_inventory.cohort import CohortInputError
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.snapshot import (
    projection as projection_module,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection import (
    project_catalog_plan,
)
from edgar_sec.pipelines.document_inventory.snapshot.errors import BaseSnapshotError
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    SNAPSHOT_ACCESSIONS_SCHEMA,
    SNAPSHOT_RELATION_VERSION,
)
from edgar_sec.pipelines.filing_catalog.paths import FilingCatalogPaths
from edgar_sec.pipelines.filing_catalog.publication import (
    plan_fingerprint,
    plan_fingerprint_from_sorted_keys,
)
from tests.support import fixture_path

_OBSERVATIONS = fixture_path("catalog") / "cohort_observations.parquet"


@pytest.fixture
def resource_profile(tmp_path: Path):
    return derive_resources(
        requested_threads=1,
        cli_overrides={"runtime.temp_directory": str(tmp_path / "duckdb-tmp")},
    )


def _build_plan(
    artifacts_root: Path,
    plan_id: str,
    table: pa.Table,
    *,
    forms: list[str] | None = None,
    scope: str = "deterministic",
) -> Path:
    catalog_paths = FilingCatalogPaths(artifacts_root)
    root = catalog_paths.plan_dir(plan_id)
    root.mkdir(parents=True)
    (root / "selection_report.json").write_text("{}", encoding="utf-8")
    if scope == "policy":
        (root / "seed_filers.csv").write_text("cik\n1\n", encoding="utf-8")
    forms = forms or sorted(set(table.column("form").to_pylist()))
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
        "scope": scope,
        "forms": forms,
        "counts": counts,
        "selected_rows": sum(counts.values()),
        "active_targets_count": sum(counts.values()),
        "unique_locators_count": len(locator_keys),
    }
    payload["plan_fingerprint"] = plan_fingerprint(payload, locator_keys)
    (root / "plan.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


def _rows(table: pa.Table) -> list[dict[str, object]]:
    return table.to_pylist()


def _publish_base_snapshot(artifacts_root: Path, accession_rows: list[dict]) -> None:
    paths = InventoryPaths(artifacts_root)
    snapshot_id = "snapshot-base"
    part = (
        paths.snapshot_root(snapshot_id)
        / "accessions"
        / "year=2024"
        / "part-00000.parquet"
    )
    part.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(accession_rows, schema=SNAPSHOT_ACCESSIONS_SCHEMA), part
    )
    manifest = {
        "snapshot_id": snapshot_id,
        "schema_version": SNAPSHOT_RELATION_VERSION,
        "accessions": [
            {
                "path": f"{snapshot_id}/accessions/year=2024/part-00000.parquet",
                "row_count": len(accession_rows),
                "sha256": file_sha256(part),
            }
        ],
    }
    (paths.snapshot_root(snapshot_id) / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    pointer = paths.current_snapshot_pointer()
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"snapshot_id": snapshot_id}), encoding="utf-8")


def _build_empty_plan(artifacts_root: Path, plan_id: str) -> None:
    catalog_paths = FilingCatalogPaths(artifacts_root)
    root = catalog_paths.plan_dir(plan_id)
    (root / "targets" / "form=10-K").mkdir(parents=True)
    (root / "selection_report.json").write_text("{}", encoding="utf-8")
    pq.write_table(
        pa.table({"document_locator_key": pa.array([], type=pa.string())}),
        root / "locator_groups.parquet",
    )
    payload = {
        "plan_id": plan_id,
        "plan_schema_version": "1.2",
        "catalog_id": "catalog-test",
        "scope": "deterministic",
        "forms": ["10-K"],
        "counts": {},
        "selected_rows": 0,
        "active_targets_count": 0,
        "unique_locators_count": 0,
    }
    payload["plan_fingerprint"] = plan_fingerprint(payload, [])
    (root / "plan.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_scale_plan(artifacts_root: Path, row_count: int) -> str:
    plan_id = "scale-plan"
    root = FilingCatalogPaths(artifacts_root).plan_dir(plan_id)
    target = root / "targets" / "form=10-K" / "data.parquet"
    target.parent.mkdir(parents=True)
    (root / "selection_report.json").write_text("{}", encoding="utf-8")
    locator_path = root / "locator_groups.parquet"
    with pq.ParquetWriter(
        locator_path, pa.schema([("document_locator_key", pa.string())])
    ) as locator_writer:
        for start in range(1, row_count + 1, 4096):
            end = min(start + 4096, row_count + 1)
            locator_writer.write_table(
                pa.table(
                    {
                        "document_locator_key": [
                            f"doc-{number:06d}" for number in range(start, end)
                        ]
                    }
                )
            )
    with pq.ParquetWriter(target, TARGET_SCHEMA) as writer:
        for start in range(1, row_count + 1, 4096):
            end = min(start + 4096, row_count + 1)
            numbers = range(start, end)
            batch_rows = list(numbers)
            rows = {
                "occurrence_id": [f"occ-{number}" for number in batch_rows],
                "document_locator_key": [f"doc-{number:06d}" for number in batch_rows],
                "source_cik": ["0000000001"] * len(batch_rows),
                "accession": [f"0000000001-26-{number:06d}" for number in batch_rows],
                "form": ["10-K"] * len(batch_rows),
                "filing_date": ["2026-01-01"] * len(batch_rows),
                "report_date": [None] * len(batch_rows),
                "primary_document": ["index.htm"] * len(batch_rows),
                "document_path": ["index.htm"] * len(batch_rows),
                "archive_url": ["https://www.sec.gov/Archives/edgar/data"]
                * len(batch_rows),
                "document_path_source": ["primary_document"] * len(batch_rows),
                "reported_size": [None] * len(batch_rows),
                "is_xbrl": [False] * len(batch_rows),
                "is_inline_xbrl": [False] * len(batch_rows),
                "is_xbrl_numeric": [False] * len(batch_rows),
            }
            writer.write_table(pa.Table.from_pydict(rows, schema=TARGET_SCHEMA))
    payload = {
        "plan_id": plan_id,
        "plan_schema_version": "1.2",
        "catalog_id": "catalog-scale",
        "scope": "deterministic",
        "forms": ["10-K"],
        "counts": {"10-K": row_count},
        "selected_rows": row_count,
        "active_targets_count": row_count,
        "unique_locators_count": row_count,
    }
    payload["plan_fingerprint"] = plan_fingerprint_from_sorted_keys(
        payload, (f"doc-{number:06d}" for number in range(1, row_count + 1))
    )
    (root / "plan.json").write_text(json.dumps(payload), encoding="utf-8")
    return plan_id


def _snapshot_row(row: dict[str, object]) -> dict[str, object]:
    return {
        "accession": str(AccessionNumber.from_any(str(row["accession"]))),
        "filing_cik": str(AccessionNumber.from_any(str(row["accession"])))[:10],
        "form": row["form"],
        "filing_date": row["filing_date"],
        "report_date": row["report_date"] or None,
        "bundle_url": None,
        "bundle_size": None,
        "index_url": "https://www.sec.gov/Archives/edgar/data/1/index.html",
        "index_sha256": "0" * 64,
        "first_indexed_by": "old-plan",
    }


def test_projection_writes_cohort_and_sorted_prefetch_order(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    plan_id = "catalog-plan"
    _build_plan(tmp_path, plan_id, table)

    projection = project_catalog_plan(
        plan_id, artifacts_root=tmp_path, profile=resource_profile
    )

    assert projection.work_order_rows == len({row["accession"] for row in _rows(table)})
    assert projection.base_snapshot_id is None
    assert projection.paths.work_order_path().is_file()
    assert projection.paths.cohort_accessions_path().is_file()
    assert projection.paths.cohort_sources_path().is_file()
    assert projection.paths.projection_manifest_path().is_file()
    work = pq.read_table(projection.paths.work_order_path())
    assert work.column("accession").to_pylist() == sorted(
        set(work.column("accession").to_pylist())
    )
    assert all("-index.html" in url for url in work.column("index_url").to_pylist())
    source_rows = pq.read_table(projection.paths.cohort_sources_path()).to_pylist()
    source_keys = {(row["accession"], row["source_cik"]) for row in source_rows}
    assert len(source_keys) == len(source_rows)


def test_policy_plan_uses_the_same_bounded_projection(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    _build_plan(tmp_path, "policy-plan", table, scope="policy")

    projection = project_catalog_plan(
        "policy-plan", artifacts_root=tmp_path, profile=resource_profile
    )

    assert projection.work_order_rows == len({row["accession"] for row in _rows(table)})


def test_identical_duplicate_source_observations_collapse(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    rows = _rows(table)
    duplicated = pa.Table.from_pylist(rows + [dict(rows[0])], schema=table.schema)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    _build_plan(first_root, "same-plan", table)
    _build_plan(second_root, "same-plan", duplicated)

    first = project_catalog_plan(
        "same-plan", artifacts_root=first_root, profile=resource_profile
    )
    second = project_catalog_plan(
        "same-plan", artifacts_root=second_root, profile=resource_profile
    )

    assert first.cohort_fingerprint == second.cohort_fingerprint
    assert first.work_order_digest == second.work_order_digest


def test_projection_retry_reuses_the_pinned_artifacts(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    _build_plan(tmp_path, "retry-plan", table)

    first = project_catalog_plan(
        "retry-plan", artifacts_root=tmp_path, profile=resource_profile
    )
    second = project_catalog_plan(
        "retry-plan", artifacts_root=tmp_path, profile=resource_profile
    )

    assert second.run_id == first.run_id
    assert second.cohort_fingerprint == first.cohort_fingerprint
    assert second.work_order_digest == first.work_order_digest


def test_known_accession_new_source_edge_changes_cohort_not_work_order(
    tmp_path: Path, resource_profile
) -> None:
    original = pq.read_table(_OBSERVATIONS)
    rows = _rows(original)
    added = dict(rows[0])
    added["source_cik"] = "0000000999"
    changed = pa.Table.from_pylist(rows + [added], schema=original.schema)
    accessions = sorted({str(row["accession"]) for row in rows})
    representative = {}
    for row in rows:
        representative.setdefault(str(row["accession"]), row)
    before_root = tmp_path / "before"
    after_root = tmp_path / "after"
    before_root.mkdir()
    after_root.mkdir()
    base_rows = [_snapshot_row(representative[accession]) for accession in accessions]
    _publish_base_snapshot(before_root, base_rows)
    _publish_base_snapshot(after_root, base_rows)
    _build_plan(before_root, "same-plan", original)
    _build_plan(after_root, "same-plan", changed)

    before = project_catalog_plan(
        "same-plan", artifacts_root=before_root, profile=resource_profile
    )
    after = project_catalog_plan(
        "same-plan", artifacts_root=after_root, profile=resource_profile
    )

    assert before.work_order_rows == after.work_order_rows == 0
    assert before.work_order_digest == after.work_order_digest
    assert before.cohort_fingerprint != after.cohort_fingerprint
    source_rows = pq.read_table(after.paths.cohort_sources_path()).to_pylist()
    assert any(row["source_cik"] == "0000000999" for row in source_rows)


def test_projection_rejects_conflicting_accession_metadata_before_manifest(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    rows = _rows(table)
    conflicting = dict(rows[0])
    conflicting["form"] = "8-K" if rows[0]["form"] != "8-K" else "10-K"
    changed = pa.Table.from_pylist(rows + [conflicting], schema=table.schema)
    _build_plan(
        tmp_path, "bad-plan", changed, forms=sorted({r["form"] for r in _rows(changed)})
    )

    with pytest.raises(CohortInputError, match="conflicting form values"):
        project_catalog_plan(
            "bad-plan", artifacts_root=tmp_path, profile=resource_profile
        )

    runs = tmp_path / "transient" / "document_inventory"
    assert not list(runs.glob("run-*/run_manifest.json"))
    assert not list(
        (runs / "projection-staging").glob("projection-*/projection_manifest.json")
    )


def test_projection_refuses_invalid_base_part_digest(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    plan_id = "catalog-plan"
    _build_plan(tmp_path, plan_id, table)
    rows = _rows(table)
    representatives = {}
    for row in rows:
        representatives.setdefault(str(row["accession"]), row)
    _publish_base_snapshot(
        tmp_path,
        [_snapshot_row(row) for row in representatives.values()],
    )
    paths = InventoryPaths(tmp_path)
    part = next(paths.snapshot_root("snapshot-base").glob("accessions/**/*.parquet"))
    part.write_bytes(b"corrupt")

    with pytest.raises(BaseSnapshotError, match="digest mismatch"):
        project_catalog_plan(plan_id, artifacts_root=tmp_path, profile=resource_profile)


def test_projection_refuses_a_plan_with_changed_locator_groups(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    plan_root = _build_plan(tmp_path, "changed-locators", table)
    locator_keys = sorted(set(table.column("document_locator_key").to_pylist()))
    locator_keys[0] = "changed-locator"
    pq.write_table(
        pa.table({"document_locator_key": locator_keys}),
        plan_root / "locator_groups.parquet",
    )

    with pytest.raises(CohortInputError, match="selection fingerprint mismatch"):
        project_catalog_plan(
            "changed-locators", artifacts_root=tmp_path, profile=resource_profile
        )


def test_semantic_fingerprint_is_independent_of_parquet_row_order(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    plan_id = "stable-plan"
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    _build_plan(first_root, plan_id, table)
    reversed_table = table.take(pa.array(list(reversed(range(table.num_rows)))))
    _build_plan(second_root, plan_id, reversed_table)

    first = project_catalog_plan(
        plan_id, artifacts_root=first_root, profile=resource_profile
    )
    second = project_catalog_plan(
        plan_id, artifacts_root=second_root, profile=resource_profile
    )

    assert first.run_id == second.run_id
    assert first.cohort_fingerprint == second.cohort_fingerprint
    assert first.work_order_digest == second.work_order_digest


def test_zero_row_plan_emits_valid_empty_relations(
    tmp_path: Path, resource_profile
) -> None:
    _build_empty_plan(tmp_path, "empty-plan")

    projection = project_catalog_plan(
        "empty-plan", artifacts_root=tmp_path, profile=resource_profile
    )

    assert projection.work_order_rows == 0
    assert pq.read_table(projection.paths.cohort_accessions_path()).num_rows == 0
    assert pq.read_table(projection.paths.cohort_sources_path()).num_rows == 0
    assert pq.read_table(projection.paths.work_order_path()).num_rows == 0


def test_zero_count_target_partition_is_valid(tmp_path: Path, resource_profile) -> None:
    table = pq.read_table(_OBSERVATIONS).slice(0, 0)
    _build_plan(tmp_path, "zero-partition", table, forms=["10-K"])

    projection = project_catalog_plan(
        "zero-partition", artifacts_root=tmp_path, profile=resource_profile
    )

    assert projection.work_order_rows == 0
    assert pq.read_table(projection.paths.cohort_accessions_path()).num_rows == 0


def test_explicit_refresh_includes_known_accessions(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    rows = _rows(table)
    representatives = {}
    for row in rows:
        representatives.setdefault(str(row["accession"]), row)
    _publish_base_snapshot(
        tmp_path,
        [_snapshot_row(row) for row in representatives.values()],
    )
    _build_plan(tmp_path, "refresh-plan", table)

    projection = project_catalog_plan(
        "refresh-plan",
        artifacts_root=tmp_path,
        profile=resource_profile,
        explicit_refresh=True,
        explicit_refresh_salt="refresh-001",
    )

    assert projection.work_order_rows == len(representatives)
    assert projection.explicit_refresh_salt == "refresh-001"


def test_conflicting_report_dates_across_sources_are_rejected(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    rows = _rows(table)
    conflicting = dict(rows[0])
    conflicting["source_cik"] = "0000000999"
    conflicting["report_date"] = "2020-01-01"
    changed = pa.Table.from_pylist(rows + [conflicting], schema=table.schema)
    _build_plan(tmp_path, "report-conflict", changed)

    with pytest.raises(CohortInputError, match="conflicting report dates"):
        project_catalog_plan(
            "report-conflict", artifacts_root=tmp_path, profile=resource_profile
        )


def test_conflicting_filing_dates_across_sources_are_rejected(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    rows = _rows(table)
    conflicting = dict(rows[0])
    conflicting["source_cik"] = "0000000999"
    conflicting["filing_date"] = "2020-01-01"
    changed = pa.Table.from_pylist(rows + [conflicting], schema=table.schema)
    _build_plan(tmp_path, "filing-date-conflict", changed)

    with pytest.raises(CohortInputError, match="conflicting filing dates"):
        project_catalog_plan(
            "filing-date-conflict", artifacts_root=tmp_path, profile=resource_profile
        )


def test_duplicate_source_observation_with_different_report_date_is_rejected(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    rows = _rows(table)
    conflicting = dict(rows[0])
    conflicting["report_date"] = None if rows[0]["report_date"] else "2020-01-01"
    changed = pa.Table.from_pylist(rows + [conflicting], schema=table.schema)
    _build_plan(tmp_path, "duplicate-report-conflict", changed)

    with pytest.raises(CohortInputError, match="duplicate source observation"):
        project_catalog_plan(
            "duplicate-report-conflict",
            artifacts_root=tmp_path,
            profile=resource_profile,
        )


@pytest.mark.parametrize(
    ("column", "value"),
    (("accession", "invalid"), ("source_cik", "not-a-cik"), ("filing_date", "invalid")),
)
def test_invalid_target_values_are_rejected(
    tmp_path: Path, resource_profile, column: str, value: str
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    rows = _rows(table)
    rows[0][column] = value
    changed = pa.Table.from_pylist(rows, schema=table.schema)
    _build_plan(tmp_path, "invalid-values", changed)

    with pytest.raises(CohortInputError, match="invalid rows"):
        project_catalog_plan(
            "invalid-values", artifacts_root=tmp_path, profile=resource_profile
        )


def test_base_filing_metadata_mismatch_is_rejected(
    tmp_path: Path, resource_profile
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    rows = _rows(table)
    representative = {}
    for row in rows:
        representative.setdefault(str(row["accession"]), row)
    base_rows = [_snapshot_row(row) for row in representative.values()]
    base_rows[0]["form"] = "OTHER"
    _publish_base_snapshot(tmp_path, base_rows)
    _build_plan(tmp_path, "metadata-mismatch", table)

    with pytest.raises(CohortInputError, match="filing metadata conflicts"):
        project_catalog_plan(
            "metadata-mismatch", artifacts_root=tmp_path, profile=resource_profile
        )


def test_interrupted_work_order_write_leaves_no_resumable_projection(
    tmp_path: Path, resource_profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pq.read_table(_OBSERVATIONS)
    _build_plan(tmp_path, "interrupted-plan", table)
    write_work_order = projection_module.write_work_order

    def interrupted_write(path, items):
        write_work_order(path, items)
        raise OSError("simulated interrupted output write")

    monkeypatch.setattr(projection_module, "write_work_order", interrupted_write)
    with pytest.raises(OSError, match="interrupted"):
        project_catalog_plan(
            "interrupted-plan", artifacts_root=tmp_path, profile=resource_profile
        )

    transient = tmp_path / "transient" / "document_inventory"
    assert not list(transient.glob("run-*/run_manifest.json"))
    assert not list((transient / "projection-staging").glob("projection-*"))


@pytest.mark.skipif(
    not os.environ.get("EDGAR_INVENTORY_SCALE_TESTS"),
    reason="opt-in 236K-accession resource acceptance",
)
def test_scale_projection_236k_accessions(
    tmp_path: Path, resource_profile, record_property
) -> None:
    plan_id = _write_scale_plan(tmp_path, 236_000)

    projection = project_catalog_plan(
        plan_id, artifacts_root=tmp_path, profile=resource_profile
    )

    record_property("peak_rss_kib", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    assert projection.work_order_rows == 236_000
    assert pq.read_table(projection.paths.cohort_accessions_path()).num_rows == 236_000
