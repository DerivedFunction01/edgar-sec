"""The Phase 2.5 entry contract, asserted rather than documented.

Phase 2.5 (document acquisition) is the largest remaining phase, and it
consumes Phase 2's published plan bundle and nothing else. That makes the
bundle an *interface* between two independently-developed phases, which means
its shape needs the same protection the rest of the codebase gets: if the
contract drifts, Phase 2.5 silently fetches the wrong documents, or fetches one
twice, or builds a URL that 404s — and none of those fail loudly here.

The contract, in full:

* A plan bundle is a complete work order. ``REQUIRED_PLAN_FILES`` are all
  present, and ``locator_groups.parquet`` is the enumeration of documents to
  fetch.
* One row per **unique document**. ``document_locator_key`` is
  ``sha256(accession || ':' || document_path)``, so a document co-filed by two
  registrants is one row, and Phase 2.5 fetches it once. This is the invariant
  §8.1.2 of the plan calls "one locator per document".
* Every row carries a fetchable ``archive_url`` over HTTPS, agreeing with the
  URL Phase 1's engine would have built.
* ``targets/form=<FORM>/data.parquet`` carries the *occurrences* — the
  registrant's claim on a document — which is one row per registrant, not per
  document. Phase 2.5 needs both: the locator list to fetch, the occurrence rows
  to attribute what came back.
* A policy plan's ``reserve_targets.parquet`` is disjoint from the active work
  order, so an acquirer that ignores the reserve never double-fetches.
* The *work order* (``locator_groups.parquet``) satisfies the same contract for
  either scope, so Phase 2.5 does not branch on scope to fetch.

The occurrence partitions are deliberately scope-specific and are **not** part of
that shared surface: a deterministic plan publishes the raw target rows while a
policy plan publishes the feature-enriched occurrence rows it selected from. The
two schemas are pinned separately, because a shared name like
"the targets contract" is exactly what let a malformed policy schema ship
unnoticed.
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

# A staged plan bundle built by either scope, for the contract tests to read.
BUNDLES = ("deterministic", "policy")

# DuckDB disambiguates a duplicate column by appending _1, _2, ... Naming that
# pattern is what turns "the policy scope emits a stray column" from a silent
# schema drift into a failed test.
DEDUPED_COLUMN = re.compile(r"^(?P<name>.+)_(?P<ordinal>\d+)$")

# Features the policy snapshot adds to a raw target row. Asserted by name so a
# "fix" that strips the feature columns -- which would satisfy a narrower
# equality check -- cannot pass.
POLICY_FEATURE_COLUMNS = (
    "form_family",
    "era",
    "size_band",
    "lifecycle_class",
    "active_years",
    "anchor_status",
    "comparison_status",
    "accession_class",
    "locator_class",
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
    """Resolve the occurrence schema the policy scope publishes from.

    ``FeatureSnapshotBuilder`` is content-addressed and reuses an existing
    snapshot, so this returns the schema the planner already wrote rather than
    rebuilding it.
    """
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
    """The columns Phase 2.5 needs, present, non-null, and HTTPS."""
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
    """The invariant that lets Phase 2.5 fetch a co-filed document once.

    ``document_locator_key`` is ``sha256(accession || ':' || document_path)``.
    Two registrants filing one document share it, and it must appear exactly
    once in the work order.
    """
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
    """Partitions carry occurrences: one row per registrant, keyed by locator.

    Phase 2.5 attributes a fetched document back through these rows, so the
    partition must key to the same locator the work order enumerates.
    """
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
    """The deterministic scope publishes exactly the declared target schema.

    Equality, not containment: this is the one scope whose output is the raw
    catalog target row, so an extra column here is unambiguously drift.
    """
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
    """The policy scope publishes its feature snapshot's occurrence schema.

    Policy plans are written from the joined feature snapshot, so the published
    partition must equal that source schema exactly. The regression this pins is
    a ``SELECT *`` over the join to the selected keys, which projected
    ``document_locator_key`` a second time and shipped a spurious
    ``document_locator_key_1`` column into the published bundle.
    """
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
    """The scopes are not interchangeable, and Phase 2.5 is told so.

    A test named "either scope satisfies the same contract" is what let a
    malformed policy schema pass review: it read one file. This one states the
    difference outright so the distinction cannot be quietly collapsed again.
    """
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
    """Phase 2.5 reads a bundle without rescanning it; these are its index keys."""
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
        # plan.json keys `counts` by the raw form name while the partition
        # directory escapes "/" to "_" ("10-K/A" -> "form=10-K_A"). A consumer
        # mapping counts onto directories must apply the same escape, so it is
        # pinned here rather than left as a trap.
        published = {entry.name for entry in (plan_dir / "targets").iterdir()}
        expected = {f"form={form_partition_name(form)}" for form in document["counts"]}
        assert published == expected


def test_both_scopes_publish_the_same_work_order_contract(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The fetch work order is scope-independent; the occurrences are not.

    Phase 2.5 must not branch on scope to *fetch*: both scopes publish the same
    locator columns. Its attribution step does branch, and
    ``test_the_two_scopes_publish_deliberately_different_occurrences`` is what
    keeps that asymmetry visible.
    """
    surfaces = set()
    for scope in BUNDLES:
        plan_dir, _ = _plan_dir(scope, catalog_snapshot, catalog_artifacts_root)
        table = pq.read_table(plan_dir / LOCATOR_GROUPS_NAME)
        surfaces.add(set(FETCH_REQUIRED) <= set(table.schema.names))
    assert surfaces == {True}
