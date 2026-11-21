"""The pinned seed input a policy plan selects against."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from edgar_sec.domain.filing_catalog.schemas import SCOPE_POLICY
from edgar_sec.engine.selection.policy import (
    SeedFiler,
    compute_seed_fingerprint,
    read_seed_filers_csv,
)
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.pipelines.cohort.ingestion import ingest_file_to_cohort
from edgar_sec.pipelines.filing_catalog.paths import (
    SEED_FILERS_FILE,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planning.policy import plan_policy
from edgar_sec.pipelines.filing_catalog.publication import (
    plan_bundle_complete,
    plan_identity,
)
from tests.pipelines.filing_catalog.planning.policy_support import (
    _artifacts_root,
    _policy,
)


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


def test_seed_cohort_replaces_configured_seed_csv_and_is_fingerprinted(
    catalog_snapshot: tuple[dict[str, object], Path],
    tmp_path: Path,
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    configured_csv = _seed_csv(tmp_path / "configured.csv", "configured")
    cohort = _seed_cohort(
        catalog_artifacts_root, tmp_path, name="cohort-seeds", cik="320193"
    )
    policy = _policy()

    meta = plan_policy(
        str(manifest["catalog_id"]),
        policy,
        catalog_artifacts_root,
        seed_cohort=cohort.cohort_id,
    )
    plan_dir = resolve_filing_catalog_paths(catalog_artifacts_root).plan_dir(
        meta["plan_id"]
    )
    seeds = read_seed_filers_csv(plan_dir / SEED_FILERS_FILE)

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
        "row_group_size": DEFAULT_ROW_GROUP_SIZE,
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
    policy = _policy()

    meta = plan_policy(
        str(manifest["catalog_id"]),
        policy,
        artifacts_root,
        seed_filers=read_seed_filers_csv(seed_path),
    )
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    sidecar = plan_dir / SEED_FILERS_FILE
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
    policy = _policy()

    first = plan_policy(
        str(manifest["catalog_id"]),
        policy,
        artifacts_root,
        seed_filers=read_seed_filers_csv(seed_path),
    )
    _seed_csv(seed_path, "renamed")
    second = plan_policy(
        str(manifest["catalog_id"]),
        policy,
        artifacts_root,
        seed_filers=read_seed_filers_csv(seed_path),
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
    policy = _policy()

    first = plan_policy(
        str(manifest["catalog_id"]),
        policy,
        artifacts_root,
        seed_filers=read_seed_filers_csv(seed_path),
    )
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(first["plan_id"])

    _seed_csv(seed_path, "edited")
    second = plan_policy(
        str(manifest["catalog_id"]),
        policy,
        artifacts_root,
        seed_filers=read_seed_filers_csv(seed_path),
    )

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
    assert read_seed_filers_csv(plan_dir / SEED_FILERS_FILE) == {}
    assert meta["seed_filer_count"] == 0
