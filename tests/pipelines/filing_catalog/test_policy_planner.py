"""Tests for the policy-scope plan: quota selection published as a plan bundle.

Stage A's deterministic plan slices on four filters and publishes eight locator
columns. These tests cover the Stage B bundle: the 18-column locator
projection, the reserve pool, the recorded policy, and the immutability and
conflict semantics that make the bundle a work order rather than a cache.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_BASE_COLUMNS,
    LOCATOR_POLICY_COLUMNS,
)
from edgar_sec.engine.selection.policy import (
    EraBand,
    SeedFiler,
    SelectionPolicy,
    compute_seed_fingerprint,
    read_seed_filers_csv,
)
from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_NAME,
    REQUIRED_PLAN_FILES,
    RESERVE_TARGETS_NAME,
    SEED_FILERS_NAME,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planner import (
    SCOPE_DETERMINISTIC,
    SCOPE_POLICY,
    plan,
    plan_policy,
)
from edgar_sec.pipelines.filing_catalog.publication import (
    PlanConflictError,
    plan_bundle_complete,
    plan_locator_keys,
)


def _policy(**overrides: object) -> SelectionPolicy:
    base: dict[str, object] = {
        "corpus_id": "policy_corpus",
        "forms": ["10-K", "8-K"],
        "era_bands": [EraBand(name="modern", start_year=2010)],
        "base_content_units": 3,
        "reserve_size": 1,
        "seed_cik_path": "__absent__",
    }
    base.update(overrides)
    return SelectionPolicy(**base)  # type: ignore[arg-type]


def test_policy_plan_publishes_a_complete_bundle(
    catalog_snapshot: tuple[dict[str, object], Path],
    tmp_path: Path,
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    policy = _policy()
    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)

    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    assert plan_bundle_complete(plan_dir)
    for name in REQUIRED_PLAN_FILES:
        assert (plan_dir / name).is_file()


def _artifacts_root(catalog_artifacts_root: Path) -> Path:
    """The artifacts root the catalog fixture was materialized into.

    Takes the shared fixture rather than walking ``parents[N]`` off the snapshot
    directory, which would encode the published depth into the test.
    """
    return catalog_artifacts_root


def test_policy_plan_locator_groups_are_the_eighteen_column_schema(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A Stage B bundle must carry the stratification dimensions a consumer
    audits a sample with, not just the identity triple Stage A emits."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    schema = pq.read_schema(plan_dir / LOCATOR_GROUPS_NAME)
    assert list(schema.names) == list(LOCATOR_POLICY_COLUMNS)
    assert len(schema.names) == 18
    assert set(LOCATOR_BASE_COLUMNS) <= set(schema.names)


def test_stage_a_locator_schema_stays_narrow(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A consumer must not be able to assume 18 columns in a deterministic plan."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan(str(manifest["catalog_id"]), artifacts_root, forms=("10-K",))
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    schema = pq.read_schema(plan_dir / LOCATOR_GROUPS_NAME)
    assert list(schema.names) == list(LOCATOR_BASE_COLUMNS)
    assert len(schema.names) == 8


def test_policy_plan_partitions_targets_by_form(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    assert set(meta["counts"]) == {"10-K", "8-K"}
    for form, count in meta["counts"].items():
        partition = plan_dir / "targets" / f"form={form}" / "data.parquet"
        assert partition.is_file()
        assert pq.read_metadata(partition).num_rows == count
    assert meta["selected_rows"] == sum(meta["counts"].values())


def test_policy_plan_records_the_policy_that_produced_it(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A plan must be self-describing: the quota profile is part of the record."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    policy = _policy(base_content_units=2)
    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)

    assert meta["scope"] == SCOPE_POLICY
    assert meta["policy_fingerprint"] == policy.policy_fingerprint
    assert meta["policy_corpus"] == policy.corpus_id
    assert meta["target_units"] == 2
    assert meta["parent_plan_id"] is None
    assert meta["seed_fingerprint"]
    assert SelectionPolicy.from_dict(meta["selection_policy"]).policy_fingerprint == (
        policy.policy_fingerprint
    )


def test_policy_plan_writes_a_reserve_pool(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    reserve = plan_dir / RESERVE_TARGETS_NAME
    assert reserve.is_file()
    assert pq.read_metadata(reserve).num_rows == meta["reserve_count"]


def test_reserve_is_disjoint_from_the_active_locators(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    active = set(
        pq.read_table(plan_dir / LOCATOR_GROUPS_NAME)[
            "document_locator_key"
        ].to_pylist()
    )
    reserve = set(
        pq.read_table(plan_dir / RESERVE_TARGETS_NAME)[
            "document_locator_key"
        ].to_pylist()
    )
    assert active.isdisjoint(reserve)


def test_a_zero_reserve_writes_no_reserve_file(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(
        str(manifest["catalog_id"]), _policy(reserve_size=0), artifacts_root
    )
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    assert not (plan_dir / RESERVE_TARGETS_NAME).exists()
    assert meta["reserve_count"] == 0


def test_policy_plan_id_is_content_derived_and_stable(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The same catalog and policy must resolve to the same bundle, not fork one."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    policy = _policy()
    first = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    second = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    assert first["plan_id"] == second["plan_id"]


def test_a_different_policy_publishes_a_different_plan(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    baseline = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    other = plan_policy(
        str(manifest["catalog_id"]),
        _policy(base_content_units=2),
        artifacts_root,
    )
    assert baseline["plan_id"] != other["plan_id"]


def test_policy_and_deterministic_scopes_never_collide(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Both scopes publish locator_groups.parquet under a content-derived id."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    deterministic = plan(str(manifest["catalog_id"]), artifacts_root, forms=("10-K",))
    policy = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    assert deterministic["plan_id"] != policy["plan_id"]
    assert deterministic["scope"] == SCOPE_DETERMINISTIC


def test_an_incomplete_bundle_is_a_conflict_not_an_overwrite(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A published bundle is immutable, even when it is damaged."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    policy = _policy()
    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    (plan_dir / LOCATOR_GROUPS_NAME).unlink()

    with pytest.raises(PlanConflictError, match="incomplete plan bundle"):
        plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)


def test_selection_report_carries_the_quota_evidence(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The report is what a reader checks to see the sample is actually balanced."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    report = json.loads(
        (plan_dir / "selection_report.json").read_text(encoding="utf-8")
    )

    assert report["scope"] == SCOPE_POLICY
    assert report["target_units"] == meta["target_units"]
    assert report["active_locators_count"] == meta["unique_locators_count"]
    assert report["unique_company_families"] >= 1
    assert "underfilled_floors" in report
    # The full coverage distribution is deliberately excluded: it is per
    # dimension and would dwarf the plan document it is embedded in.
    assert "coverage_distributions" not in report


def test_an_unsatisfiable_floor_is_reported_in_the_plan(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A published plan must not assert a quota it never met."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    policy = _policy(floors={"era": {"prehistoric": 2}})
    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    assert meta["underfilled_floors"]["era"]["prehistoric"]["deficit"] == 2


def test_seed_filers_are_recorded_in_the_plan(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    seeds = {"0000000019": SeedFiler(cik="0000000019", seed_group="anchor")}
    policy = _policy()
    with_seeds = plan_policy(
        str(manifest["catalog_id"]), policy, artifacts_root, seed_filers=seeds
    )
    without = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    assert with_seeds["seed_fingerprint"] != without["seed_fingerprint"]
    assert with_seeds["plan_id"] != without["plan_id"]


def test_policy_plan_rejects_a_policy_with_no_forms(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    policy = _policy()
    policy.forms = []
    with pytest.raises(ValueError, match="at least one form"):
        plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)


def test_plan_rejects_an_unsafe_catalog_reference(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    with pytest.raises(ValueError, match="unsafe identifier"):
        plan_policy("../../etc", _policy(), artifacts_root)


# --- the pinned seed input -------------------------------------------------


def _seed_csv(path: Path, rows: list[tuple[str, str]]) -> Path:
    path.write_text(
        "cik,name,seed_group,coverage_tags,notes\n"
        + "".join(f"{cik},{name},default,,\n" for cik, name in rows),
        encoding="utf-8",
    )
    return path


def test_a_policy_plan_publishes_its_normalized_seed_set(
    catalog_snapshot: tuple[dict[str, object], Path],
    tmp_path: Path,
    catalog_artifacts_root: Path,
) -> None:
    """The plan carries the seed set it selected against, not a path to one."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    seed_path = _seed_csv(tmp_path / "seed-cik.csv", [("0000000001", "Acme")])
    policy = _policy(seed_cik_path=str(seed_path))

    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    sidecar = plan_dir / SEED_FILERS_NAME
    assert sidecar.is_file()
    published = read_seed_filers_csv(sidecar)
    assert set(published) == {"0000000001"}
    assert published["0000000001"].name == "Acme"
    assert meta["seed_filer_count"] == 1
    assert meta["seed_fingerprint"] == compute_seed_fingerprint(published)


def test_editing_the_seed_csv_changes_the_plan_identity(
    catalog_snapshot: tuple[dict[str, object], Path],
    tmp_path: Path,
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    seed_path = _seed_csv(tmp_path / "seed-cik.csv", [("0000000001", "Acme")])

    first = plan_policy(
        str(manifest["catalog_id"]),
        _policy(seed_cik_path=str(seed_path)),
        artifacts_root,
    )
    _seed_csv(seed_path, [("0000000001", "Renamed")])
    second = plan_policy(
        str(manifest["catalog_id"]),
        _policy(seed_cik_path=str(seed_path)),
        artifacts_root,
    )
    assert first["seed_fingerprint"] != second["seed_fingerprint"]
    assert first["plan_id"] != second["plan_id"]


def test_a_seed_plan_reused_after_the_csv_changes_is_refused(
    catalog_snapshot: tuple[dict[str, object], Path],
    tmp_path: Path,
    catalog_artifacts_root: Path,
) -> None:
    """The identity guard that stops a moved file silently changing a plan."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    seed_path = _seed_csv(tmp_path / "seed-cik.csv", [("0000000001", "Acme")])
    policy = _policy(seed_cik_path=str(seed_path))

    first = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(first["plan_id"])

    _seed_csv(seed_path, [("0000000001", "Acme"), ("0000000002", "Beta")])
    second = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)

    assert second["plan_id"] != first["plan_id"]
    # The old bundle is untouched and still verifies against its own recorded
    # selection; it simply is not the bundle this request resolves to.
    assert plan_bundle_complete(plan_dir)


def test_a_plan_with_no_seed_file_publishes_an_empty_seed_set(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    assert read_seed_filers_csv(plan_dir / SEED_FILERS_NAME) == {}
    assert meta["seed_filer_count"] == 0


# --- determinism -----------------------------------------------------------


# --- advisory inventory feasibility ---------------------------------------


def _advisory(plan_dir: Path) -> dict[str, object]:
    report = json.loads(
        (plan_dir / "selection_report.json").read_text(encoding="utf-8")
    )
    return dict(report["inventory_feasibility"])


def test_a_floor_policy_reports_inventory_feasibility(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The report says whether the corpus could have met the quota, and by how much."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(floors={"era": {"modern": 2, "ancient": 5}}),
        artifacts_root,
    )
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    advisory = _advisory(plan_dir)
    assert advisory["checked"] is True
    assert advisory["floors"]["era"]["modern"]["feasible"] is True
    assert advisory["floors"]["era"]["ancient"] == {
        "required": 5,
        "available": 0,
        "feasible": False,
        "deficit": 5,
    }
    assert advisory["infeasible_floors"] == ["ancient"]


def test_feasibility_is_advisory_and_does_not_fail_a_plan(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """An impossible floor must not turn a fresh plan into a refusal.

    A fresh policy plan publishes what the corpus could supply and records the
    shortfall; the feasibility report explains it. Only an expansion is refused
    for failing to reach its target.
    """
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(floors={"era": {"ancient": 500}}),
        artifacts_root,
    )
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    assert _advisory(plan_dir)["infeasible_floors"] == ["ancient"]
    assert plan_bundle_complete(plan_dir)


def test_a_policy_with_no_quotas_skips_the_inventory(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Nothing to predict, so the report says so instead of scanning."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    assert _advisory(plan_dir) == {
        "checked": False,
        "reason": "policy declares no floors or composites",
    }


def test_a_composite_policy_reports_feasibility(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(composites=[{"filters": {"era": "modern"}, "min": 2}]),
        artifacts_root,
    )
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    advisory = _advisory(plan_dir)
    assert advisory["checked"] is True
    assert advisory["composites"][0]["filters"] == {"era": "modern"}
    assert advisory["infeasible_composites"] == []


def test_an_occurrence_only_composite_is_refused_at_the_policy(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A stratum the selector could never match is refused where it is written.

    Composites are drawn from locator_features, which has no accession_class
    column. Without this check the failure surfaces as a DuckDB Binder Error from
    inside selection, naming a column rather than the policy field that caused it.
    """
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    with pytest.raises(ValueError, match="locator_features"):
        plan_policy(
            str(manifest["catalog_id"]),
            _policy(composites=[{"filters": {"accession_class": "high"}, "min": 1}]),
            artifacts_root,
        )


def test_a_sic_code_composite_is_accepted(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """sic_code is locator-grain, so a composite on it is a valid policy."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(composites=[{"filters": {"sic_code": "3571"}, "min": 1}]),
        artifacts_root,
    )
    assert meta["plan_id"]


def test_a_policy_rebuild_into_an_independent_root_is_identical(
    catalog_snapshot: tuple[dict[str, object], Path],
    tmp_path: Path,
    sample_source: Path,
) -> None:
    """Two builds from separate inputs must agree on the whole bundle.

    The existing same-root test cannot see drift: the second call reuses the
    published bundle instead of rebuilding it, so it proves reuse works, not
    that selection is reproducible. This rebuilds.
    """
    manifest, _ = catalog_snapshot
    policy = _policy()

    # Two independent artifacts roots, each with its own catalog snapshot, so
    # nothing about the publication is shared between the two builds.
    first_root = tmp_path / "a"
    second_root = tmp_path / "b"
    materialize(sample_source, first_root)
    materialize(sample_source, second_root)

    first = plan_policy(str(manifest["catalog_id"]), policy, first_root)
    second = plan_policy(str(manifest["catalog_id"]), policy, second_root)

    assert first["plan_id"] == second["plan_id"]
    assert first["plan_fingerprint"] == second["plan_fingerprint"]
    assert first["counts"] == second["counts"]

    first_dir = resolve_filing_catalog_paths(first_root).plan_dir(first["plan_id"])
    second_dir = resolve_filing_catalog_paths(second_root).plan_dir(second["plan_id"])
    assert plan_locator_keys(first_dir) == plan_locator_keys(second_dir)
    for partition in sorted(first_dir.glob("targets/form=*/data.parquet")):
        mirror = second_dir / partition.relative_to(first_dir)
        assert pq.read_table(partition).to_pylist() == pq.read_table(mirror).to_pylist()
