from pathlib import Path

import pytest

from edgar_sec.pipelines.document_planning.paths import (
    catalog_form_partition_name,
    resolve_document_planning_paths,
    resolve_catalog_paths,
    resolve_inventory_paths,
    validate_profile_id,
)


@pytest.mark.parametrize("value", ["../escape", "a/b", "", ".", "..", "a b"])
def test_profile_id_rejects_non_component_values(value: str) -> None:
    with pytest.raises(ValueError):
        validate_profile_id(value)


def test_paths_resolve_policy_and_plan_paths_from_roots(tmp_path: Path) -> None:
    paths = resolve_document_planning_paths(tmp_path, tmp_path / "configured-artifacts")

    assert paths.profiles_root == tmp_path / "policies" / "document_targets"
    assert (
        paths.plan_dir("plan_1")
        == tmp_path / "configured-artifacts" / "document_planning" / "plans" / "plan_1"
    )
    assert paths.plan_manifest_path("plan_1").name == "plan.json"


def test_source_paths_use_their_own_pipeline_resolvers(tmp_path: Path) -> None:
    catalog = resolve_catalog_paths(tmp_path)
    inventory = resolve_inventory_paths(tmp_path)

    assert catalog.plans_root == tmp_path / "filing_catalog" / "plans"
    assert inventory.snapshots_root == tmp_path / "document_inventory" / "snapshots"
    assert catalog_form_partition_name("S-1/A") == "S-1_A"
