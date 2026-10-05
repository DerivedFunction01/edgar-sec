"""Catalog bundle reader: validation, streaming, and deterministic chunk identity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths

from edgar_sec.infra.storage.parquet import read_parquet_schema
from edgar_sec.pipelines.document_storage.catalog_plan import (
    CatalogPlan,
    CatalogPlanError,
)


def test_a_deterministic_bundle_reads_every_locator(era_plan_dir: Path) -> None:
    plan = CatalogPlan(era_plan_dir, chunk_size=64)
    chunks = list(plan.iter_chunks())
    locators = [locator for chunk in chunks for locator in chunk.locators]
    assert len(locators) == plan.metadata.locator_count
    assert all(locator.archive_url for locator in locators)


def test_chunk_ids_and_membership_are_stable_across_reads(era_plan_dir: Path) -> None:
    first = [
        chunk.chunk_id
        for chunk in CatalogPlan(era_plan_dir, chunk_size=8).iter_chunks()
    ]
    second = [
        chunk.chunk_id
        for chunk in CatalogPlan(era_plan_dir, chunk_size=8).iter_chunks()
    ]
    assert first == second
    assert all(chunk_id.startswith("cat-") for chunk_id in first)


def test_chunk_size_changes_chunk_identity_and_membership(era_plan_dir: Path) -> None:
    small = list(CatalogPlan(era_plan_dir, chunk_size=4).iter_chunks())
    large = list(CatalogPlan(era_plan_dir, chunk_size=64).iter_chunks())
    assert [chunk.chunk_id for chunk in small] != [chunk.chunk_id for chunk in large]
    assert all(len(chunk.locators) <= 4 for chunk in small)
    assert len(large) == 1


def test_a_co_filer_locator_is_one_work_item_holding_every_occurrence(
    era_plan_dir: Path,
) -> None:
    chunks = list(CatalogPlan(era_plan_dir, chunk_size=64).iter_chunks())
    group = next(
        chunk for chunk in chunks if len(chunk.occurrences) > len(chunk.locators)
    )
    by_key: dict[str, list[str]] = {}
    for occurrence in group.occurrences:
        by_key.setdefault(occurrence.doc_id, []).append(occurrence.occurrence_id)
    co_filer_key = next(key for key, ids in by_key.items() if len(ids) > 1)
    locator = next(
        item for item in group.locators if item.document_locator_key == co_filer_key
    )
    assert len(by_key[co_filer_key]) == 2
    assert (
        sum(1 for item in group.locators if item.document_locator_key == co_filer_key)
        == 1
    )


def test_occurrences_key_on_their_locator_key(era_plan_dir: Path) -> None:
    plan = CatalogPlan(era_plan_dir, chunk_size=64)
    locator_keys = {locator.document_locator_key for locator in plan.iter_locators()}
    for chunk in plan.iter_chunks():
        for occurrence in chunk.occurrences:
            assert occurrence.doc_id in locator_keys


def test_every_locator_row_is_fetched_by_its_published_archive_url(
    era_plan_dir: Path,
) -> None:
    plan = CatalogPlan(era_plan_dir, chunk_size=64)
    for locator in plan.iter_locators():
        assert locator.archive_url.endswith(f"/{locator.document_path}"), (
            locator.archive_url
        )


def test_a_work_order_reports_a_chunk_count_matching_a_full_read(
    era_plan_dir: Path,
) -> None:
    plan = CatalogPlan(era_plan_dir, chunk_size=5)
    assert plan.chunk_count == len(list(plan.iter_chunks()))


def test_locators_by_key_reads_only_what_is_named(era_plan_dir: Path) -> None:
    plan = CatalogPlan(era_plan_dir, chunk_size=64)
    wanted = [locator.document_locator_key for locator in plan.iter_locators()][:2]
    found = plan.locators_by_key(wanted)
    assert sorted(found) == sorted(wanted)
    assert plan.locators_by_key(["absent"]) == {}
    assert plan.locators_by_key([]) == {}


def test_a_co_filer_group_names_one_representative_cik(era_plan_dir: Path) -> None:
    plan = CatalogPlan(era_plan_dir, chunk_size=64)
    occurrences: dict[str, set[str]] = {}
    for chunk in plan.iter_chunks():
        for occurrence in chunk.occurrences:
            occurrences.setdefault(occurrence.doc_id, set()).add(
                occurrence.source_cik.to_10digit()
            )
    assert any(len(ciks) > 1 for ciks in occurrences.values())


def test_a_non_positive_chunk_size_is_refused(era_plan_dir: Path) -> None:
    with pytest.raises(CatalogPlanError, match="chunk_size must be positive"):
        CatalogPlan(era_plan_dir, chunk_size=0)


def _rewrite_plan_json(plan_dir: Path, mutate: Any) -> None:
    path = plan_dir / "plan.json"
    published = json.loads(path.read_text(encoding="utf-8"))
    mutate(published)
    path.write_text(json.dumps(published), encoding="utf-8")


def test_an_unsupported_plan_schema_version_is_refused(era_plan_dir: Path) -> None:
    _rewrite_plan_json(era_plan_dir, lambda m: m.update(plan_schema_version="0.1"))
    with pytest.raises(CatalogPlanError, match="unsupported plan schema version"):
        CatalogPlan(era_plan_dir, chunk_size=8)


def test_a_plan_id_that_disagrees_with_its_directory_is_refused(
    era_plan_dir: Path,
) -> None:
    _rewrite_plan_json(era_plan_dir, lambda m: m.update(plan_id="elsewhere"))
    with pytest.raises(CatalogPlanError, match="does not match bundle directory"):
        CatalogPlan(era_plan_dir, chunk_size=8)


def test_an_unknown_scope_is_refused(era_plan_dir: Path) -> None:
    _rewrite_plan_json(era_plan_dir, lambda m: m.update(scope="speculative"))
    with pytest.raises(CatalogPlanError, match="unknown plan scope"):
        CatalogPlan(era_plan_dir, chunk_size=8)


def test_a_missing_target_partition_is_refused(era_plan_dir: Path) -> None:
    partition = sorted((era_plan_dir / "targets").glob("form=*/data.parquet"))[0]
    partition.unlink()
    with pytest.raises(CatalogPlanError, match="declared target partition is missing"):
        CatalogPlan(era_plan_dir, chunk_size=8)


def test_a_plan_recording_no_targets_is_refused(era_plan_dir: Path) -> None:
    _rewrite_plan_json(era_plan_dir, lambda m: m.update(counts={}))
    with pytest.raises(CatalogPlanError, match="records no target counts"):
        CatalogPlan(era_plan_dir, chunk_size=8)


def test_a_count_that_disagrees_with_its_partition_is_refused(
    era_plan_dir: Path,
) -> None:
    def inflate(published: dict[str, Any]) -> None:
        published["counts"] = {
            form: count + 1 for form, count in published["counts"].items()
        }

    _rewrite_plan_json(era_plan_dir, inflate)
    with pytest.raises(CatalogPlanError, match="rows; plan.json declares"):
        CatalogPlan(era_plan_dir, chunk_size=8)


def test_a_locator_row_without_a_target_is_refused(era_plan_dir: Path) -> None:
    _append_locator_group_row(era_plan_dir)
    with pytest.raises(CatalogPlanError, match="hold no target row"):
        CatalogPlan(era_plan_dir, chunk_size=8)


def test_a_target_row_without_a_locator_is_refused(era_plan_dir: Path) -> None:
    _drop_locator_group_row(era_plan_dir)
    with pytest.raises(CatalogPlanError, match="reference a locator the plan does not"):
        CatalogPlan(era_plan_dir, chunk_size=8)


def _drop_locator_group_row(plan_dir: Path) -> None:
    import pyarrow.parquet as pq

    path = plan_dir / "locator_groups.parquet"
    table = pq.read_table(path)
    pq.write_table(table.slice(1), path)


def _append_locator_group_row(plan_dir: Path) -> None:
    import pyarrow.parquet as pq

    path = plan_dir / "locator_groups.parquet"
    table = pq.read_table(path)
    # A copy of a real row under a key no target references.
    orphan = table.slice(0, 1).set_column(
        0, "document_locator_key", pa.array(["0" * 64])
    )
    pq.write_table(pa.concat_tables([table, orphan]), path)


def test_a_reserve_targets_file_never_enters_the_work_order(
    era_plan_dir: Path,
) -> None:
    import pyarrow.parquet as pq

    targets = sorted((era_plan_dir / "targets").glob("form=*/data.parquet"))[0]
    pq.write_table(pq.read_table(targets), era_plan_dir / "reserve_targets.parquet")
    plan = CatalogPlan(era_plan_dir, chunk_size=64)
    assert all("reserve" not in locator.archive_url for locator in plan.iter_locators())


def test_a_policy_bundle_reads_with_its_wider_locator_schema(
    catalog_artifacts_root: Path, universe_roster: Path, tmp_path: Path
) -> None:
    from edgar_sec.domain.filing_catalog.schemas import (
        LOCATOR_POLICY_COLUMNS,
        SCOPE_POLICY,
    )
    from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy
    from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
    from edgar_sec.pipelines.filing_catalog.planner import plan_policy
    from tests.support import era_submission_metadata

    source = era_submission_metadata(tmp_path / "era.parquet")
    catalog_id = str(materialize(source, catalog_artifacts_root)["catalog_id"])
    meta = plan_policy(
        catalog_id,
        SelectionPolicy(
            corpus_id="storage_policy",
            forms=["10-K", "8-K"],
            era_bands=[EraBand(name="era", start_year=2000, end_year=2004)],
            base_content_units=8,
            reserve_size=1,
            seed_cik_path="__absent__",
        ),
        catalog_artifacts_root,
    )
    plan_dir = resolve_filing_catalog_paths(catalog_artifacts_root).plan_dir(
        meta["plan_id"]
    )
    published = json.loads((plan_dir / "plan.json").read_text(encoding="utf-8"))
    assert published["scope"] == SCOPE_POLICY

    plan = CatalogPlan(plan_dir, chunk_size=64)
    locators = list(plan.iter_locators())
    assert locators
    assert tuple(
        read_parquet_schema(plan_dir / "locator_groups.parquet").names
    ) == tuple(LOCATOR_POLICY_COLUMNS)
    assert len(locators) <= plan.metadata.locator_count
