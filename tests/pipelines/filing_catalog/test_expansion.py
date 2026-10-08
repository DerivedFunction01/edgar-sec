"""Target-plan expansion: lineage, and a child that never drops a parent locator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from edgar_sec.engine.selection.policy import (
    EraBand,
    SeedFiler,
    compute_seed_fingerprint,
    load_seed_cik_csv,
    read_seed_filers_csv,
)
from edgar_sec.pipelines.filing_catalog.expansion import (
    ExpansionLineage,
    ParentPlanError,
    expand,
    prepare_parent,
    read_expansion_metadata,
    validate_target,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    EXPANSION_METADATA_NAME,
    LOCATOR_GROUPS_NAME,
    SEED_FILERS_NAME,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planner import plan_policy
from edgar_sec.pipelines.filing_catalog.publication import (
    plan_fingerprint,
    plan_locator_keys,
)
from tests.pipelines.filing_catalog.test_policy_planner import _policy


def _root(catalog_artifacts_root: Path) -> Path:
    return catalog_artifacts_root


def _publish_parent(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
    **overrides: Any,
) -> tuple[Path, dict[str, Any]]:
    artifacts_root = _root(catalog_artifacts_root)
    catalog_id = str(catalog_snapshot[0]["catalog_id"])
    meta = plan_policy(catalog_id, _policy(**overrides), artifacts_root)
    paths = resolve_filing_catalog_paths(artifacts_root)
    return paths.plan_dir(meta["plan_id"]), meta


def test_child_plan_retains_every_parent_locator(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The important guarantee: expansion adds, it never replaces."""
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    parent_keys = set(plan_locator_keys(parent_dir))

    child = expand(parent_dir, 4, artifacts_root=_root(catalog_artifacts_root))
    child_dir = resolve_filing_catalog_paths(_root(catalog_artifacts_root)).plan_dir(
        child["plan_id"]
    )
    child_keys = set(plan_locator_keys(child_dir))

    assert parent_keys
    assert parent_keys <= child_keys
    assert len(child_keys) > len(parent_keys)


def test_expansion_records_its_lineage(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    parent_dir, parent_meta = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    child = expand(parent_dir, 4, artifacts_root=_root(catalog_artifacts_root))
    child_dir = resolve_filing_catalog_paths(_root(catalog_artifacts_root)).plan_dir(
        child["plan_id"]
    )

    lineage = read_expansion_metadata(child_dir)
    assert lineage["parent_plan_id"] == parent_meta["plan_id"]
    assert lineage["child_plan_id"] == child["plan_id"]
    assert lineage["target_units"] == 4
    assert lineage["parent_locator_count"] == parent_meta["unique_locators_count"]
    assert lineage["retained_locator_count"] == lineage["parent_locator_count"]
    assert lineage["added_locator_count"] == (
        lineage["child_locator_count"] - lineage["parent_locator_count"]
    )
    assert lineage["expansion_ratio"] == 2.0


def test_child_plan_json_records_its_parent(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A plan's provenance must be readable from the plan itself."""
    parent_dir, parent_meta = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    child = expand(parent_dir, 4, artifacts_root=_root(catalog_artifacts_root))
    child_dir = resolve_filing_catalog_paths(_root(catalog_artifacts_root)).plan_dir(
        child["plan_id"]
    )
    document = json.loads((child_dir / PLAN_FILE_NAME).read_text(encoding="utf-8"))
    assert document["parent_plan_id"] == parent_meta["plan_id"]
    assert document["parent_plan_fingerprint"]
    assert document["level"] == 2


def test_a_root_plan_has_no_lineage_record(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    assert read_expansion_metadata(parent_dir) == {}
    assert not (parent_dir / EXPANSION_METADATA_NAME).exists()


# --------------------------------------------------------- parent compatibility


def _rewrite_plan(plan_dir: Path, mutate: Any) -> None:
    """Apply ``mutate`` to a published ``plan.json`` in place."""
    document = json.loads((plan_dir / PLAN_FILE_NAME).read_text(encoding="utf-8"))
    mutate(document)
    (plan_dir / PLAN_FILE_NAME).write_text(
        json.dumps(document, indent=2, sort_keys=True), encoding="utf-8"
    )


def _child_plan_ids(artifacts_root: Path, exclude: str) -> set[str]:
    plans_root = resolve_filing_catalog_paths(artifacts_root).plans_root
    return {
        child.name
        for child in plans_root.iterdir()
        if child.is_dir() and child.name != exclude
    }


def test_a_downgraded_parent_is_refused_even_when_the_sidecar_survives(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A 1.0 bundle has no seed sidecar, so an absent fingerprint must not match."""
    artifacts_root = _root(catalog_artifacts_root)
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    _rewrite_plan(
        parent_dir,
        lambda document: (
            document.__setitem__("plan_schema_version", "1.0"),
            document.pop("seed_fingerprint"),
        ),
    )
    before = _child_plan_ids(artifacts_root, parent_dir.name)

    with pytest.raises(ParentPlanError, match="republish the parent plan"):
        expand(parent_dir, 4, artifacts_root=artifacts_root)
    assert _child_plan_ids(artifacts_root, parent_dir.name) == before


def test_a_downgraded_parent_reports_the_schema_mismatch_not_a_missing_file(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The sidecar read must not precede the version check and mask the schema."""
    artifacts_root = _root(catalog_artifacts_root)
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    _rewrite_plan(
        parent_dir,
        lambda document: document.__setitem__("plan_schema_version", "1.0"),
    )
    (parent_dir / SEED_FILERS_NAME).unlink()

    with pytest.raises(ParentPlanError) as failure:
        expand(parent_dir, 4, artifacts_root=artifacts_root)
    message = str(failure.value)
    assert "1.0" in message
    assert "republish the parent plan" in message
    assert "not found" not in message


@pytest.mark.parametrize("version", [None, "0.9", "1.1", ""])
def test_only_the_current_schema_is_expandable(
    catalog_snapshot: tuple[dict[str, Any], Path],
    version: str | None,
    catalog_artifacts_root: Path,
) -> None:
    """Older, newer, absent and empty all fail closed with no fallback."""
    artifacts_root = _root(catalog_artifacts_root)
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )

    def drop_or_set(document: dict[str, Any]) -> None:
        if version is None:
            document.pop("plan_schema_version", None)
        else:
            document["plan_schema_version"] = version

    _rewrite_plan(parent_dir, drop_or_set)
    with pytest.raises(ParentPlanError, match="republish the parent plan"):
        expand(parent_dir, 4, artifacts_root=artifacts_root)


@pytest.mark.parametrize(
    "field", ["policy_corpus", "seed_fingerprint", "plan_fingerprint", "catalog_id"]
)
def test_a_current_parent_missing_a_required_field_is_refused(
    catalog_snapshot: tuple[dict[str, Any], Path],
    field: str,
    catalog_artifacts_root: Path,
) -> None:
    """A required field absent at the current schema is malformed, not optional."""
    artifacts_root = _root(catalog_artifacts_root)
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    _rewrite_plan(parent_dir, lambda document: document.pop(field))

    with pytest.raises(ParentPlanError, match=f"{field}"):
        expand(parent_dir, 4, artifacts_root=artifacts_root)


def test_a_tampered_parent_fingerprint_is_refused(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A missing fingerprint must not be recomputed over altered locators."""
    artifacts_root = _root(catalog_artifacts_root)
    parent_dir, parent_meta = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    _rewrite_plan(
        parent_dir,
        lambda document: document.__setitem__("plan_fingerprint", "0" * 16),
    )

    with pytest.raises(ParentPlanError, match="fingerprint does not match"):
        expand(parent_dir, 4, artifacts_root=artifacts_root)
    assert parent_meta["plan_fingerprint"] != "0" * 16


def test_a_parent_with_a_missing_sidecar_is_a_parent_plan_error(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """An incomplete but current-schema bundle is still a bundle that must be fixed."""
    artifacts_root = _root(catalog_artifacts_root)
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    (parent_dir / SEED_FILERS_NAME).unlink()

    with pytest.raises(ParentPlanError) as failure:
        expand(parent_dir, 4, artifacts_root=artifacts_root)
    assert "seed sidecar is unusable" in str(failure.value)


def test_a_malformed_parent_sidecar_is_a_parent_plan_error(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A truncated sidecar is reported as the bundle fault it is."""
    artifacts_root = _root(catalog_artifacts_root)
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    (parent_dir / SEED_FILERS_NAME).write_text("cik\n0000320193\n", encoding="utf-8")

    with pytest.raises(ParentPlanError, match="seed sidecar is unusable"):
        expand(parent_dir, 4, artifacts_root=artifacts_root)


def test_the_schema_gate_protects_direct_prepare_parent_callers(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """``prepare_parent`` is public; it must not be a way around the gate."""
    parent_dir, parent_meta = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    _rewrite_plan(
        parent_dir,
        lambda document: document.__setitem__("plan_schema_version", "1.0"),
    )

    with pytest.raises(ParentPlanError, match="republish the parent plan"):
        prepare_parent(
            parent_dir,
            _policy(),
            4,
            str(parent_meta["catalog_id"]),
            compute_seed_fingerprint({}),
        )


def test_duplicate_expansion_is_idempotent(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Re-expanding to the same size must reuse the published child, not fork one."""
    artifacts_root = _root(catalog_artifacts_root)
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    first = expand(parent_dir, 4, artifacts_root=artifacts_root)
    second = expand(parent_dir, 4, artifacts_root=artifacts_root)
    assert first["plan_id"] == second["plan_id"]


def test_different_parents_produce_different_children(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The child's identity must bind to its parent, not just its target size."""
    artifacts_root = _root(catalog_artifacts_root)
    catalog_id = str(catalog_snapshot[0]["catalog_id"])
    paths = resolve_filing_catalog_paths(artifacts_root)

    small = plan_policy(catalog_id, _policy(base_content_units=2), artifacts_root)
    large = plan_policy(catalog_id, _policy(base_content_units=3), artifacts_root)
    first = expand(paths.plan_dir(small["plan_id"]), 4, artifacts_root=artifacts_root)
    second = expand(paths.plan_dir(large["plan_id"]), 4, artifacts_root=artifacts_root)
    assert first["plan_id"] != second["plan_id"]


def test_expanding_below_the_parent_size_is_refused(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A smaller request is a contraction, and truncating would drop documents."""
    parent_dir, parent_meta = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=3
    )
    with pytest.raises(ParentPlanError, match="cannot be smaller than the parent"):
        expand(
            parent_dir,
            int(parent_meta["unique_locators_count"]) - 1,
            artifacts_root=_root(catalog_artifacts_root),
        )


def test_a_non_positive_target_is_refused(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    with pytest.raises(ValueError, match="target_units must be positive"):
        expand(parent_dir, 0, artifacts_root=_root(catalog_artifacts_root))


def test_a_deterministic_parent_cannot_be_expanded(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A deterministic plan has no policy to extend and no quota to preserve."""
    from edgar_sec.pipelines.filing_catalog.planner import plan

    artifacts_root = _root(catalog_artifacts_root)
    catalog_id = str(catalog_snapshot[0]["catalog_id"])
    meta = plan(catalog_id, artifacts_root, forms=("10-K",))
    parent_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    with pytest.raises(ParentPlanError, match="requires a policy-driven parent"):
        expand(parent_dir, 10, artifacts_root=artifacts_root)


def test_a_parent_without_a_recorded_policy_cannot_be_expanded(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    document = json.loads((parent_dir / PLAN_FILE_NAME).read_text(encoding="utf-8"))
    del document["selection_policy"]
    (parent_dir / PLAN_FILE_NAME).write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ParentPlanError, match="does not record its selection policy"):
        expand(parent_dir, 4, artifacts_root=_root(catalog_artifacts_root))


def test_a_child_with_different_forms_is_refused(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Combining selections built against different form sets is meaningless."""
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    parent_meta = json.loads((parent_dir / PLAN_FILE_NAME).read_text(encoding="utf-8"))
    parent_meta["forms"] = ["10-Q"]
    (parent_dir / PLAN_FILE_NAME).write_text(json.dumps(parent_meta), encoding="utf-8")

    with pytest.raises(ParentPlanError, match="same forms"):
        prepare_parent(
            parent_dir,
            _policy(),
            4,
            str(catalog_snapshot[0]["catalog_id"]),
            parent_meta["seed_fingerprint"],
        )


def test_a_child_with_a_different_corpus_is_refused(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    with pytest.raises(ParentPlanError, match="same policy corpus"):
        prepare_parent(
            parent_dir,
            _policy(corpus_id="a-different-corpus"),
            4,
            str(catalog_snapshot[0]["catalog_id"]),
            compute_seed_fingerprint({}),
        )


def test_a_child_with_a_different_seed_set_is_refused(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    with pytest.raises(ParentPlanError, match="same seed CIK set"):
        prepare_parent(
            parent_dir,
            _policy(),
            4,
            str(catalog_snapshot[0]["catalog_id"]),
            "a-different-seed-fingerprint",
        )


def test_a_child_that_cannot_reach_its_target_publishes_nothing(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A caller asking for 5,000 locators must not silently receive a smaller plan."""
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    artifacts_root = _root(catalog_artifacts_root)
    with pytest.raises(ParentPlanError, match="could not reach target_units"):
        expand(parent_dir, 5_000, artifacts_root=artifacts_root)

    paths = resolve_filing_catalog_paths(artifacts_root)
    assert not paths.plan_dir("5_000").exists()


def test_validate_target_only_constrains_an_expansion() -> None:
    validate_target(None, selected_count=1, target_units=10)
    with pytest.raises(ParentPlanError, match="could not reach target_units"):
        validate_target("/somewhere", selected_count=1, target_units=10)


def test_plan_fingerprint_binds_to_the_selection() -> None:
    """Two runs that selected differently must not share a fingerprint."""
    meta = {"plan_id": "p", "catalog_id": "c", "scope": "policy"}
    assert plan_fingerprint(meta, ["b", "a"]) == plan_fingerprint(meta, ["a", "b"])
    assert plan_fingerprint(meta, ["a"]) != plan_fingerprint(meta, ["a", "b"])
    assert len(plan_fingerprint(meta, ["a"])) == 32


def test_plan_locator_keys_rejects_a_directory_without_locators(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="locator groups not found"):
        plan_locator_keys(tmp_path)


def test_expansion_lineage_ratios() -> None:
    lineage = ExpansionLineage(
        parent_plan_id="p",
        parent_plan_fingerprint="f",
        target_units=10,
        parent_locator_count=4,
        child_locator_count=8,
    )
    assert lineage.added_locator_count == 4
    assert lineage.expansion_ratio == 2.0
    assert ExpansionLineage("p", "f", 1, 0, 0).expansion_ratio == 0.0


def test_expanded_child_keeps_the_18_column_locator_schema(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Expansion must not silently degrade the artifact a consumer audits."""
    from edgar_sec.domain.filing_catalog.schemas import LOCATOR_POLICY_COLUMNS

    artifacts_root = _root(catalog_artifacts_root)
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    child = expand(parent_dir, 4, artifacts_root=artifacts_root)
    child_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(child["plan_id"])
    schema = pq.read_schema(child_dir / LOCATOR_GROUPS_NAME)
    assert list(schema.names) == list(LOCATOR_POLICY_COLUMNS)


def test_prepare_parent_derives_the_child_level_and_lineage(
    catalog_snapshot: tuple[dict[str, Any], Path],
    catalog_artifacts_root: Path,
) -> None:
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, base_content_units=2
    )
    parent_meta, parent_keys, child_policy = prepare_parent(
        parent_dir,
        _policy(),
        6,
        str(catalog_snapshot[0]["catalog_id"]),
        compute_seed_fingerprint({}),
    )
    assert child_policy.base_content_units == 6
    assert child_policy.level == 2
    assert child_policy.parent_plan_id == parent_meta["plan_id"]
    assert child_policy.parent_plan_fingerprint
    assert parent_keys


# --- seeded expansion ------------------------------------------------------


def _seed_csv(path: Path, rows: list[tuple[str, str]] = ()) -> Path:
    """A seed also defines the family index, so the names must exist in the corpus."""
    rows = rows or [("0000320193", "APPLE FIXTURE INC")]
    path.write_text(
        "cik,name,seed_group,coverage_tags,notes\n"
        + "".join(f"{cik},{name},default,,\n" for cik, name in rows),
        encoding="utf-8",
    )
    return path


def test_a_seeded_parent_expands_from_its_own_published_seed_set(
    catalog_snapshot: tuple[dict[str, Any], Path],
    tmp_path: Path,
    catalog_artifacts_root: Path,
) -> None:
    """Expansion inherits the parent's seed set, not the file it came from."""
    artifacts_root = _root(catalog_artifacts_root)
    catalog_id = str(catalog_snapshot[0]["catalog_id"])
    seed_path = _seed_csv(tmp_path / "seed-cik.csv")

    parent = plan_policy(
        catalog_id, _policy(seed_cik_path=str(seed_path)), artifacts_root
    )
    parent_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(
        parent["plan_id"]
    )
    assert parent["seed_filer_count"] == 1
    # The bundle carries the seed set, so the configured manifest is expendable.
    seed_path.unlink()

    child = expand(parent_dir, 4, artifacts_root=artifacts_root)
    child_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(child["plan_id"])
    assert child["seed_fingerprint"] == parent["seed_fingerprint"]
    assert read_seed_filers_csv(child_dir / SEED_FILERS_NAME) == {
        "0000320193": SeedFiler(cik="0000320193")
    }
    assert set(plan_locator_keys(parent_dir)) <= set(plan_locator_keys(child_dir))


def test_expanding_a_plan_whose_seed_set_was_edited_is_refused(
    catalog_snapshot: tuple[dict[str, Any], Path],
    tmp_path: Path,
    catalog_artifacts_root: Path,
) -> None:
    """A different seed set is a different plan, not a compatible one."""
    artifacts_root = _root(catalog_artifacts_root)
    catalog_id = str(catalog_snapshot[0]["catalog_id"])
    seed_path = _seed_csv(tmp_path / "seed-cik.csv")

    parent = plan_policy(
        catalog_id,
        _policy(base_content_units=2, seed_cik_path=str(seed_path)),
        artifacts_root,
    )
    parent_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(
        parent["plan_id"]
    )

    other = _seed_csv(
        tmp_path / "other.csv", [("0000019617", "JPMORGAN FIXTURE CHASE")]
    )
    with pytest.raises(ParentPlanError, match="same seed CIK set"):
        expand(
            parent_dir,
            4,
            artifacts_root=artifacts_root,
            seed_filers=load_seed_cik_csv(other),
        )


# --- era bands resolved in the parent ---------------------------------------


def test_a_child_inherits_the_bands_its_parent_resolved(
    catalog_snapshot: tuple[dict[str, Any], Path], catalog_artifacts_root: Path
) -> None:
    """A plan embeds its resolved bands, since era is baked into the snapshot."""
    parent_dir, parent_meta = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, era_bands=[], base_content_units=2
    )
    draft = _policy(era_bands=[], base_content_units=2)
    assert draft.derives_era_bands

    child = expand(parent_dir, 4, artifacts_root=_root(catalog_artifacts_root))

    parent_bands = parent_meta["selection_policy"]["era_bands"]
    assert parent_bands, "the parent must have resolved bands to inherit"
    assert child["selection_policy"]["era_bands"] == parent_bands


def test_a_child_that_declares_different_bands_is_refused(
    catalog_snapshot: tuple[dict[str, Any], Path], catalog_artifacts_root: Path
) -> None:
    """Editing the strata changes what a plan means, so it is a new root plan."""
    parent_dir, _ = _publish_parent(
        catalog_snapshot, catalog_artifacts_root, era_bands=[], base_content_units=2
    )
    with pytest.raises(ParentPlanError, match="differs from the parent"):
        prepare_parent(
            parent_dir,
            _policy(era_bands=[EraBand(name="elsewhere", start_year=2015)]),
            4,
            str(catalog_snapshot[0]["catalog_id"]),
            compute_seed_fingerprint({}),
        )


def test_a_child_that_declares_the_same_bands_is_accepted(
    catalog_snapshot: tuple[dict[str, Any], Path], catalog_artifacts_root: Path
) -> None:
    """Restating the parent's bands is agreement, not a change."""
    bands = [EraBand(name="only", start_year=2010)]
    parent_dir, _ = _publish_parent(
        catalog_snapshot,
        catalog_artifacts_root,
        era_bands=bands,
        base_content_units=2,
    )
    _, _, child = prepare_parent(
        parent_dir,
        _policy(era_bands=bands),
        4,
        str(catalog_snapshot[0]["catalog_id"]),
        compute_seed_fingerprint({}),
    )
    assert child.era_bands == bands
    assert child.base_content_units == 4
