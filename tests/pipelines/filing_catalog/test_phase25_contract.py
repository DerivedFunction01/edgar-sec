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
* Either scope, deterministic or policy, satisfies the same contract, so
  Phase 2.5 does not branch on scope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.sec_urls import archives_url
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


def _publish(
    scope: str, catalog_id: str, artifacts_root: Path
) -> tuple[Path, dict[str, Any]]:
    if scope == "deterministic":
        meta = plan(catalog_id, artifacts_root, forms=("10-K", "10-Q", "8-K", "10-K/A"))
    else:
        policy = SelectionPolicy(
            corpus_id="contract_corpus",
            forms=["10-K", "10-Q", "8-K", "10-K/A"],
            era_bands=[EraBand(name="modern", start_year=2010)],
            base_content_units=3,
            reserve_size=1,
            seed_cik_path="__absent__",
        )
        meta = plan_policy(catalog_id, policy, artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    return plan_dir, meta


def _plan_dir(
    scope: str, catalog_snapshot: tuple[dict[str, Any], Path]
) -> tuple[Path, dict[str, Any]]:
    manifest, snapshot_dir = catalog_snapshot
    return _publish(scope, str(manifest["catalog_id"]), snapshot_dir.parent.parent)


@pytest.mark.parametrize("scope", BUNDLES)
def test_bundle_is_a_complete_work_order(
    scope: str, catalog_snapshot: tuple[dict[str, Any], Path]
) -> None:
    plan_dir, _ = _plan_dir(scope, catalog_snapshot)
    assert plan_bundle_complete(plan_dir)
    for name in REQUIRED_PLAN_FILES:
        assert (plan_dir / name).is_file(), f"Phase 2.5 requires {name}"


@pytest.mark.parametrize("scope", BUNDLES)
def test_every_locator_row_is_fetchable(
    scope: str, catalog_snapshot: tuple[dict[str, Any], Path]
) -> None:
    """The columns Phase 2.5 needs, present, non-null, and HTTPS."""
    plan_dir, _ = _plan_dir(scope, catalog_snapshot)
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
    scope: str, catalog_snapshot: tuple[dict[str, Any], Path]
) -> None:
    """The invariant that lets Phase 2.5 fetch a co-filed document once.

    ``document_locator_key`` is ``sha256(accession || ':' || document_path)``.
    Two registrants filing one document share it, and it must appear exactly
    once in the work order.
    """
    plan_dir, _ = _plan_dir(scope, catalog_snapshot)
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
    scope: str, catalog_snapshot: tuple[dict[str, Any], Path]
) -> None:
    """Partitions carry occurrences: one row per registrant, keyed by locator.

    Phase 2.5 attributes a fetched document back through these rows, so the
    partition must key to the same locator the work order enumerates.
    """
    plan_dir, meta = _plan_dir(scope, catalog_snapshot)
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


def test_reserve_is_disjoint_from_the_work_order(
    catalog_snapshot: tuple[dict[str, Any], Path],
) -> None:
    """An acquirer that ignores the reserve must never double-fetch."""
    plan_dir, meta = _plan_dir("policy", catalog_snapshot)
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
) -> None:
    """Phase 2.5 reads a bundle without rescanning it; these are its index keys."""
    import json

    for scope in BUNDLES:
        plan_dir, meta = _plan_dir(scope, catalog_snapshot)
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


def test_either_scope_satisfies_the_same_contract(
    catalog_snapshot: tuple[dict[str, Any], Path],
) -> None:
    """Phase 2.5 must not have to branch on which scope produced the plan."""
    surfaces = set()
    for scope in BUNDLES:
        plan_dir, _ = _plan_dir(scope, catalog_snapshot)
        table = pq.read_table(plan_dir / LOCATOR_GROUPS_NAME)
        surfaces.add(set(FETCH_REQUIRED) <= set(table.schema.names))
    assert surfaces == {True}
