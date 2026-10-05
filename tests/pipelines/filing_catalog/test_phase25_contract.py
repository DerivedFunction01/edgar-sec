"""The published plan bundle as an acquirer's work order: one row per unique
document, with the scope-specific occurrence partitions pinned separately.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.filing_catalog.schemas import TARGET_COLUMNS
from edgar_sec.domain.sec_urls import archives_url
from edgar_sec.engine.selection.features import FeatureSnapshotBuilder
from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_NAME,
    PLAN_FILE_NAME,
    REQUIRED_PLAN_FILES,
    RESERVE_TARGETS_NAME,
    form_partition_name,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planner import plan, plan_policy
from edgar_sec.pipelines.filing_catalog.publication import plan_bundle_complete

# The four columns an acquirer cannot do its job without.
FETCH_REQUIRED = (
    "document_locator_key",
    "representative_accession",
    "document_path",
    "archive_url",
)

BUNDLES = ("deterministic", "policy")

# DuckDB disambiguates a duplicate as `name_1`, so naming that pattern catches drift.
DEDUPED_COLUMN = re.compile(r"^(?P<name>.+)_(?P<ordinal>\d+)$")

# Named explicitly so a "fix" that strips the feature columns cannot pass. `locator_class`
# is absent on purpose: it has locator grain only, so it is not an occurrence column.
POLICY_FEATURE_COLUMNS = (
    "form_family",
    "era",
    "size_band",
    "lifecycle_class",
)


def _contract_policy() -> SelectionPolicy:
    return SelectionPolicy(
        corpus_id="contract_corpus",
        forms=["10-K", "10-Q", "8-K", "10-K/A"],
        era_bands=[EraBand(name="modern", start_year=2010)],
        base_content_units=3,
        reserve_size=1,
        seed_cik_path="__absent__",
    )


def _publish(
    scope: str, catalog_id: str, artifacts_root: Path
) -> tuple[Path, dict[str, Any]]:
    if scope == "deterministic":
        meta = plan(catalog_id, artifacts_root, forms=("10-K", "10-Q", "8-K", "10-K/A"))
    else:
        meta = plan_policy(catalog_id, _contract_policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    return plan_dir, meta


def _feature_occurrence_columns(catalog_id: str, artifacts_root: Path) -> list[str]:
    """The planner already built the snapshot, so read its schema instead."""
    paths = resolve_filing_catalog_paths(artifacts_root)
    builder = FeatureSnapshotBuilder(
        target_root=paths.snapshot_targets_dir(catalog_id),
        profile_path=paths.snapshot_profiles_file(catalog_id),
        output_root=paths.catalog_root,
        policy=_contract_policy(),
    )
    snapshot = builder.build()
    return pq.read_schema(snapshot.occurrence_features).names


def _plan_dir(
    scope: str,
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> tuple[Path, dict[str, Any]]:
    manifest, _ = catalog_snapshot
    return _publish(scope, str(manifest["catalog_id"]), catalog_artifacts_root)


@pytest.mark.parametrize("scope", BUNDLES)
def test_bundle_is_a_complete_work_order(
    scope: str,
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    plan_dir, _ = _plan_dir(scope, catalog_snapshot, catalog_artifacts_root)
    assert plan_bundle_complete(plan_dir)
    for name in REQUIRED_PLAN_FILES:
        assert (plan_dir / name).is_file(), f"Phase 2.5 requires {name}"


@pytest.mark.parametrize("scope", BUNDLES)
def test_every_locator_row_is_fetchable(
    scope: str,
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The columns an acquirer needs, present, non-null, and HTTPS."""
    plan_dir, _ = _plan_dir(scope, catalog_snapshot, catalog_artifacts_root)
    table = pq.read_table(plan_dir / LOCATOR_GROUPS_NAME)
    for column in FETCH_REQUIRED:
        assert column in table.schema.names, f"Phase 2.5 needs {column}"
        assert table.column(column).null_count == 0, (
            f"null {column} would stall a fetch"
        )

    for row in table.to_pylist():
        assert row["archive_url"].startswith("https://")
        assert row["document_path"]


@pytest.mark.parametrize("scope", BUNDLES)
def test_occurrences_collapse_to_one_locator_per_document(
    scope: str,
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The key is sha256(accession || ':' || document_path), so co-filers share it."""
    plan_dir, _ = _plan_dir(scope, catalog_snapshot, catalog_artifacts_root)
    rows = pq.read_table(plan_dir / LOCATOR_GROUPS_NAME).to_pylist()
    keys = [row["document_locator_key"] for row in rows]

    assert keys, "an empty plan gives Phase 2.5 nothing to fetch"
    assert len(keys) == len(set(keys)), (
        "a document appears twice; it would be fetched twice"
    )
    assert keys == sorted(keys), "an unsorted work order is not reproducible"

    for row in rows:
        expected = archives_url(
            row["representative_cik"],
            row["representative_accession"],
            row["document_path"],
        )
        assert row["archive_url"] == expected


@pytest.mark.parametrize("scope", BUNDLES)
def test_occurrences_are_the_registrants_claim_not_the_document(
    scope: str,
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A fetched document is attributed back through these rows, so the keys must match."""
    plan_dir, meta = _plan_dir(scope, catalog_snapshot, catalog_artifacts_root)
    partitions = sorted(plan_dir.glob("targets/form=*/data.parquet"))
    assert partitions, "Phase 2.5 has no per-form targets"

    locators = set(
        pq.read_table(plan_dir / LOCATOR_GROUPS_NAME)[
            "document_locator_key"
        ].to_pylist()
    )
    total = 0
    for partition in partitions:
        table = pq.read_table(partition)
        assert "occurrence_id" in table.schema.names
        assert "document_locator_key" in table.schema.names
        keys = table.column("document_locator_key").to_pylist()
        assert set(keys) <= locators, (
            "a target references a locator not in the work order"
        )
        total += table.num_rows

    assert total == meta["selected_rows"] == meta["active_targets_count"]


def test_deterministic_targets_publish_the_raw_target_schema(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Equality, not containment: an extra column here is unambiguously drift."""
    plan_dir, _ = _plan_dir("deterministic", catalog_snapshot, catalog_artifacts_root)
    for partition in sorted(plan_dir.glob("targets/form=*/data.parquet")):
        names = pq.read_schema(partition).names
        assert names == list(TARGET_COLUMNS), (
            f"{partition.name} does not match TARGET_COLUMNS"
        )


def test_policy_targets_publish_the_feature_occurrence_schema(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = catalog_artifacts_root
    expected = _feature_occurrence_columns(str(manifest["catalog_id"]), artifacts_root)

    plan_dir, _ = _plan_dir("policy", catalog_snapshot, catalog_artifacts_root)
    for partition in sorted(plan_dir.glob("targets/form=*/data.parquet")):
        names = pq.read_schema(partition).names

        deduped = [
            f"{name} -> {match.group('name')}"
            for name in names
            if (match := DEDUPED_COLUMN.match(name)) and match.group("name") in names
        ]
        assert not deduped, (
            f"{partition.name} repeats a column as a numbered copy: {deduped}"
        )
        assert names == expected, (
            f"{partition.name} does not match the feature occurrence schema"
        )
        missing = [column for column in POLICY_FEATURE_COLUMNS if column not in names]
        assert not missing, f"policy targets lost their feature columns: {missing}"


def test_the_two_scopes_publish_deliberately_different_occurrences(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    deterministic_plan, _ = _plan_dir(
        "deterministic", catalog_snapshot, catalog_artifacts_root
    )
    policy_plan, _ = _plan_dir("policy", catalog_snapshot, catalog_artifacts_root)

    deterministic = pq.read_schema(
        min(deterministic_plan.glob("targets/form=*/data.parquet"))
    ).names
    policy = pq.read_schema(min(policy_plan.glob("targets/form=*/data.parquet"))).names

    assert deterministic == list(TARGET_COLUMNS)
    assert set(TARGET_COLUMNS) < set(policy), (
        "policy scope is expected to widen the raw target schema with features"
    )


def test_reserve_is_disjoint_from_the_work_order(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """An acquirer that ignores the reserve must never double-fetch."""
    plan_dir, meta = _plan_dir("policy", catalog_snapshot, catalog_artifacts_root)
    reserve = plan_dir / RESERVE_TARGETS_NAME
    assert reserve.is_file()

    active = set(
        pq.read_table(plan_dir / LOCATOR_GROUPS_NAME)[
            "document_locator_key"
        ].to_pylist()
    )
    reserved = set(pq.read_table(reserve)["document_locator_key"].to_pylist())
    assert active.isdisjoint(reserved)
    assert meta["reserve_count"] == len(reserved)


def test_plan_json_states_what_the_bundle_contains(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Read without rescanning, so these are the keys an acquirer indexes by."""
    import json

    for scope in BUNDLES:
        plan_dir, meta = _plan_dir(scope, catalog_snapshot, catalog_artifacts_root)
        document = json.loads((plan_dir / PLAN_FILE_NAME).read_text(encoding="utf-8"))
        for key in (
            "plan_schema_version",
            "plan_id",
            "catalog_id",
            "scope",
            "counts",
            "selected_rows",
            "active_targets_count",
            "unique_locators_count",
        ):
            assert key in document, f"{scope} plan.json is missing {key}"
        assert document["unique_locators_count"] == meta["unique_locators_count"]
        # `counts` is keyed by raw form name; directories escape "/" to "_".
        published = {entry.name for entry in (plan_dir / "targets").iterdir()}
        expected = {f"form={form_partition_name(form)}" for form in document["counts"]}
        assert published == expected


def test_both_scopes_publish_the_same_work_order_contract(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    surfaces = set()
    for scope in BUNDLES:
        plan_dir, _ = _plan_dir(scope, catalog_snapshot, catalog_artifacts_root)
        table = pq.read_table(plan_dir / LOCATOR_GROUPS_NAME)
        surfaces.add(set(FETCH_REQUIRED) <= set(table.schema.names))
    assert surfaces == {True}
