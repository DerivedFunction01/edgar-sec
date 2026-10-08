"""Quota-policy planning and the plan bundle it publishes."""

from __future__ import annotations

import hashlib
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
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.ingestion import ingest_file_to_cohort
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_NAME,
    REQUIRED_PLAN_FILES,
    RESERVE_TARGETS_NAME,
    SEED_FILERS_NAME,
    SELECTION_REPORT_NAME,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planner import (
    SCOPE_DETERMINISTIC,
    SCOPE_POLICY,
    plan,
    plan_policy,
)
from edgar_sec.pipelines.cohort.family_index import publish_family_index
from edgar_sec.pipelines.filing_catalog.publication import (
    PlanConflictError,
    plan_bundle_complete,
    plan_identity,
    plan_locator_keys,
)
from tests.support import published_universe


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
    assert meta["family_index_id"]
    for name in REQUIRED_PLAN_FILES:
        assert (plan_dir / name).is_file()


def _artifacts_root(catalog_artifacts_root: Path) -> Path:
    """The shared fixture, not ``parents[N]``, which would pin the published depth."""
    return catalog_artifacts_root


def test_policy_plan_locator_groups_are_the_eighteen_column_schema(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Plan locator groups include the selection dimensions for audit."""
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
    # Per-dimension coverage would dwarf the plan document it is embedded in.
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


def _seed_csv(path: Path, group: str) -> Path:
    path.write_text(
        f"cik,seed_group,coverage_tags,notes\n0000000001,{group},,\n",
        encoding="utf-8",
    )
    return path


def _seed_cohort(
    artifacts_root: Path, tmp_path: Path, *, name: str, cik: str
) -> object:
    paths = resolve_cohort_paths(artifacts_root)
    source = tmp_path / f"{name}.csv"
    source.write_text(f"cik,name\n{cik},entity\n", encoding="utf-8")
    return ingest_file_to_cohort(
        source,
        catalog=CohortCatalog(paths),
        paths=paths,
        name=name,
    ).cohort


def test_seed_cohort_replaces_configured_seed_csv_and_is_fingerprinted(
    catalog_snapshot: tuple[dict[str, object], Path],
    tmp_path: Path,
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    configured_csv = _seed_csv(tmp_path / "configured.csv", "configured")
    policy = _policy(seed_cik_path=str(configured_csv))
    cohort = _seed_cohort(
        catalog_artifacts_root, tmp_path, name="cohort-seeds", cik="320193"
    )

    meta = plan_policy(
        str(manifest["catalog_id"]),
        policy,
        catalog_artifacts_root,
        seed_cohort=cohort.cohort_id,
    )
    plan_dir = resolve_filing_catalog_paths(catalog_artifacts_root).plan_dir(
        meta["plan_id"]
    )
    seeds = read_seed_filers_csv(plan_dir / SEED_FILERS_NAME)

    assert set(seeds) == {"0000320193"}
    seed = seeds["0000320193"]
    assert seed.seed_group == "cohort"
    assert seed.coverage_tags == cohort.name
    assert seed.notes == f"From cohort {cohort.cohort_id}"
    assert meta["seed_cohort_id"] == cohort.cohort_id
    assert meta["seed_cohort_dataset_sha256"] == cohort.dataset_sha256
    assert meta["seed_fingerprint"] == compute_seed_fingerprint(seeds)
    request = {
        "catalog_id": str(manifest["catalog_id"]),
        "scope": SCOPE_POLICY,
        "policy_fingerprint": policy.policy_fingerprint,
        "seed_fingerprint": meta["seed_fingerprint"],
        "family_index_id": meta["family_index_id"],
        "plan_schema_version": meta["plan_schema_version"],
        "seed_cohort_id": cohort.cohort_id,
        "seed_cohort_dataset_sha256": cohort.dataset_sha256,
    }
    assert meta["plan_id"] == plan_identity(request)
    assert (
        meta["request_fingerprint"]
        == hashlib.sha256(
            json.dumps(request, sort_keys=True).encode("utf-8")
        ).hexdigest()
    )


def test_a_policy_plan_publishes_its_normalized_seed_set(
    catalog_snapshot: tuple[dict[str, object], Path],
    tmp_path: Path,
    catalog_artifacts_root: Path,
) -> None:
    """The plan carries the seed set it selected against, not a path to one."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    seed_path = _seed_csv(tmp_path / "seed-cik.csv", "default")
    policy = _policy(seed_cik_path=str(seed_path))

    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    sidecar = plan_dir / SEED_FILERS_NAME
    assert sidecar.is_file()
    published = read_seed_filers_csv(sidecar)
    assert set(published) == {"0000000001"}
    assert meta["seed_filer_count"] == 1
    assert meta["seed_fingerprint"] == compute_seed_fingerprint(published)


def test_a_different_target_or_level_still_separates_plan_identities(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Dropping a request key is safe only if the fingerprint still separates them."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    catalog = str(manifest["catalog_id"])

    base = plan_policy(catalog, _policy(), artifacts_root)
    bigger = plan_policy(catalog, _policy(base_content_units=4), artifacts_root)
    deeper = plan_policy(catalog, _policy(level=2), artifacts_root)

    assert len({base["plan_id"], bigger["plan_id"], deeper["plan_id"]}) == 3


def test_editing_the_seed_csv_changes_the_plan_identity(
    catalog_snapshot: tuple[dict[str, object], Path],
    tmp_path: Path,
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    seed_path = _seed_csv(tmp_path / "seed-cik.csv", "default")

    first = plan_policy(
        str(manifest["catalog_id"]),
        _policy(seed_cik_path=str(seed_path)),
        artifacts_root,
    )
    _seed_csv(seed_path, "renamed")
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
    seed_path = _seed_csv(tmp_path / "seed-cik.csv", "default")
    policy = _policy(seed_cik_path=str(seed_path))

    first = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(first["plan_id"])

    _seed_csv(seed_path, "edited")
    second = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)

    assert second["plan_id"] != first["plan_id"]
    # The old bundle still verifies; it is not what this request resolves to.
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
    """A fresh plan publishes what the corpus could supply and records the shortfall."""
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
    """A same-root call reuses the bundle, so it proves reuse, not reproducibility."""
    manifest, _ = catalog_snapshot
    policy = _policy()

    # Two independent roots, each with its own catalog snapshot.
    first_root = tmp_path / "a"
    second_root = tmp_path / "b"
    materialize(sample_source, first_root)
    materialize(sample_source, second_root)
    for root in (first_root, second_root):
        published_universe(root)
        paths = resolve_cohort_paths(root)
        publish_family_index(catalog=CohortCatalog(paths), paths=paths)

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


# --- the date selection and derived era bands --------------------------------


def _selection_report(
    artifacts_root: Path, meta: dict[str, object]
) -> dict[str, object]:
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(
        str(meta["plan_id"])
    )
    return json.loads((plan_dir / SELECTION_REPORT_NAME).read_text("utf-8"))


def _derived_bands_policy(**overrides: object) -> SelectionPolicy:
    return _policy(era_bands=[], **overrides)


def test_a_policy_declaring_no_bands_gets_bands_from_the_catalog(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    """The fixture's 10-K and 10-Q report in 2023 and 2024, so those years tile."""
    manifest, _ = catalog_snapshot
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _derived_bands_policy(forms=["10-K", "10-Q"]),
        catalog_artifacts_root,
    )
    bands = SelectionPolicy.from_dict(meta["selection_policy"]).era_bands
    assert bands, "automatic mode must resolve bands"
    assert bands[0].start_year == 2023
    assert bands[-1].end_year == 2025
    # The plan records the bands used, so a later rebuild cannot disagree.
    assert (
        SelectionPolicy.from_dict(meta["selection_policy"]).derives_era_bands is False
    )
    assert (
        meta["policy_fingerprint"]
        == SelectionPolicy.from_dict(meta["selection_policy"]).policy_fingerprint
    )


def test_derived_bands_follow_the_reachable_years(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    """Only a 10-Q carries the fixture's 2024 date, so that form is declared."""
    manifest, _ = catalog_snapshot
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _derived_bands_policy(
            forms=["10-Q"],
            date_selection=[
                {
                    "kind": "absolute",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                }
            ],
        ),
        catalog_artifacts_root,
    )
    bands = SelectionPolicy.from_dict(meta["selection_policy"]).era_bands
    assert [band.start_year for band in bands] == [2024]


def test_a_declared_band_list_is_left_alone(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    manifest, _ = catalog_snapshot
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(era_bands=[EraBand(name="declared", start_year=1990, end_year=1991)]),
        catalog_artifacts_root,
    )
    bands = SelectionPolicy.from_dict(meta["selection_policy"]).era_bands
    assert [band.name for band in bands] == ["declared"]


def test_a_date_selection_narrows_what_the_plan_selects(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    """The fixture reports 2023, so a 2024 window publishes empty, not stale rows."""
    manifest, _ = catalog_snapshot
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(
            date_selection=[
                {
                    "kind": "absolute",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                }
            ]
        ),
        catalog_artifacts_root,
    )
    report = _selection_report(catalog_artifacts_root, meta)
    assert report["date_selection_text"] == "2024-01-01..2024-12-31"
    assert report["form_era_allocation"]["cell_count"] == 0
    assert meta["selected_rows"] == 0


def test_the_report_states_the_selection_and_the_allocation(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    manifest, _ = catalog_snapshot
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), catalog_artifacts_root)
    report = _selection_report(catalog_artifacts_root, meta)
    assert report["date_selection"] == []
    assert report["date_selection_text"] == ""
    assert report["era_band_count"] == len(meta["selection_policy"]["era_bands"])
    assert report["derives_era_bands"] is False
    allocation = report["form_era_allocation"]
    assert {"cells", "cell_count", "equal_quota", "unallocated"} <= set(allocation)


def test_a_policy_document_without_the_new_field_is_still_readable(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    """A draft written before the field existed is a policy, not an error."""
    manifest, _ = catalog_snapshot
    unfiltered = _policy().to_dict()
    unfiltered.pop("date_selection")
    meta = plan_policy(
        str(manifest["catalog_id"]),
        SelectionPolicy.from_dict(unfiltered),
        catalog_artifacts_root,
    )
    assert meta["selection_policy"]["date_selection"] == []


def test_a_selection_that_reaches_nothing_falls_back_to_the_catalogs_years(
    catalog_snapshot: tuple[dict[str, object], Path], catalog_artifacts_root: Path
) -> None:
    """The fallback is the catalog's own years, never a synthetic band."""
    manifest, _ = catalog_snapshot
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _derived_bands_policy(
            date_selection=[
                {
                    "kind": "absolute",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                }
            ]
        ),
        catalog_artifacts_root,
    )
    bands = SelectionPolicy.from_dict(meta["selection_policy"]).era_bands
    assert [band.start_year for band in bands] == [2023, 2024]
    assert meta["selected_rows"] == 0
