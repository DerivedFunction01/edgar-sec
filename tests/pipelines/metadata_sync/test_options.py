"""The options boundary: one typed model, resolved once, no environment reads. A
setting read from a module constant instead becomes the canonical plan record.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.pipelines.metadata_sync.manifest import compile_cik_cohort
from edgar_sec.pipelines.metadata_sync.options import (
    BundleRunPaths,
    PlanOptions,
    SelectedCohort,
    augment_options,
    derive_plan_id,
    plan_options,
    read_bundle_plan_id,
    resolve_chunk_size,
    resolve_cohort,
    run_options,
)
from edgar_sec.pipelines.metadata_sync.paths import (
    resolve_metadata_paths,
    resolve_run_paths,
)
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from tests.support import fixture_path, roster_of

MINI = str(fixture_path("cik_sec_mini.csv"))


# ---------------------------------------------------------------- plan options


def test_an_explicit_chunk_size_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    assert (
        plan_options(input_path=MINI, artifacts_root=tmp_path, chunk_size=5).chunk_size
        == 5
    )


def test_the_registry_supplies_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    assert plan_options(input_path=MINI, artifacts_root=tmp_path).chunk_size == 7


def test_the_code_default_applies_with_no_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("RUNTIME_CHUNK_SIZE", raising=False)
    assert (
        plan_options(input_path=MINI, artifacts_root=tmp_path).chunk_size
        == DEFAULT_CHUNK_SIZE
    )


def test_resolve_chunk_size_is_pure_over_its_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    assert resolve_chunk_size(5) == 5
    assert resolve_chunk_size(None) == 7


def test_plan_options_carry_no_worker_field() -> None:
    """A worker count is a property of the machine, so it cannot reach plan identity."""
    assert not hasattr(PlanOptions, "workers")
    assert [field for field in PlanOptions.__slots__] == [
        "input_path",
        "registry_id",
        "universe",
        "artifacts_root",
        "chunk_size",
        "limit",
    ]


def test_a_cohort_reference_is_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "1")
    with pytest.raises(ValueError, match="--input, --roster, or --universe"):
        plan_options().roster()


def test_a_limit_is_applied_before_identity_is_derived(tmp_path: Path) -> None:
    """A bounded cohort is a different cohort, and must hash as one."""
    full = resolve_cohort(
        plan_options(input_path=MINI, artifacts_root=tmp_path, chunk_size=2)
    )
    limited = resolve_cohort(
        plan_options(input_path=MINI, artifacts_root=tmp_path, chunk_size=2, limit=2)
    )
    assert full.roster.row_count == 4
    assert limited.roster.row_count == 2
    assert limited.roster.roster_id != full.roster.roster_id
    assert limited.input_fingerprint == full.input_fingerprint
    assert full.input_name == limited.input_name == "cik_sec_mini.csv"


def test_a_limit_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="limit"):
        resolve_cohort(plan_options(input_path=MINI, artifacts_root=tmp_path, limit=0))


def test_a_registry_cohort_names_its_source(tmp_path: Path) -> None:
    roster = roster_of(("0000005555",), ("NEWCO",))
    cohort = SelectedCohort.from_registry("reg1", roster)
    assert cohort.input_name == "registry:reg1"
    assert cohort.input_fingerprint == roster.roster_id
    assert cohort.roster.range_ciks(0, cohort.roster.row_count) == ("0000005555",)


def test_a_csv_cohort_keeps_its_fingerprint(tmp_path: Path) -> None:
    """The fingerprint is the reproducibility root of a run, so it stays a digest."""
    cohort = resolve_cohort(plan_options(input_path=MINI, artifacts_root=tmp_path))
    expected = compile_cik_cohort(
        MINI, metadata_paths=resolve_metadata_paths(tmp_path / "expected")
    )
    assert cohort.input_fingerprint == expected.input_fingerprint
    assert cohort.roster.roster_id == expected.roster_id


def test_lineage_is_empty_for_a_csv_cohort(tmp_path: Path) -> None:
    assert plan_options(input_path=MINI, artifacts_root=tmp_path).lineage() == {
        "registry_id": ""
    }
    assert plan_options(registry_id="reg1", artifacts_root=tmp_path).lineage() == {
        "registry_id": "reg1"
    }


# ------------------------------------------------------------------ universe


def _publish_universe(root: Path) -> str:
    """Publish a real snapshot so a cohort reference resolves."""
    from edgar_sec.pipelines.metadata_sync.source_registry import (
        SOURCE_UNIVERSE_URL,
        refresh_cik_lookup_universe,
    )
    from tests.support import FakeSession, build_test_http, fixture_path

    session = FakeSession()
    session.register_bytes(
        SOURCE_UNIVERSE_URL, fixture_path("cik_lookup_universe_mini.txt").read_bytes()
    )
    metadata = resolve_metadata_paths(root)
    manifest = refresh_cik_lookup_universe(
        metadata_paths=metadata, client=build_test_http(session)
    )
    return str(manifest["snapshot_id"])


def test_universe_needs_a_published_snapshot(tmp_path: Path) -> None:
    """Planning stays network-free, so an absent snapshot is an instruction."""
    with pytest.raises(ValueError, match="sources refresh --source cik_lookup"):
        resolve_cohort(plan_options(universe=True, artifacts_root=tmp_path))


def test_universe_resolves_a_published_snapshot(tmp_path: Path) -> None:
    snapshot_id = _publish_universe(tmp_path)
    cohort = resolve_cohort(plan_options(universe=True, artifacts_root=tmp_path))
    assert cohort.input_fingerprint == snapshot_id
    assert "cik_lookup" in cohort.input_name


def test_universe_refuses_to_mix_with_a_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--universe alone"):
        plan_options(universe=True, input_path=MINI, artifacts_root=tmp_path).roster()


def test_a_universe_plan_carries_the_source_snapshot_id(tmp_path: Path) -> None:
    snapshot_id = _publish_universe(tmp_path)
    assert plan_options(universe=True, artifacts_root=tmp_path).lineage() == {
        "registry_id": "",
        "source_snapshot_id": snapshot_id,
    }


def test_run_options_re_derive_from_a_universe_cohort(tmp_path: Path) -> None:
    _publish_universe(tmp_path)
    options = run_options(universe=True, chunk_size=2, artifacts_root=tmp_path)
    assert options.plan_id


# ----------------------------------------------------------------- run options


def test_a_plan_id_can_be_re_derived_from_a_cohort(tmp_path: Path) -> None:
    derived = derive_plan_id(
        plan_options(input_path=MINI, artifacts_root=tmp_path, chunk_size=2)
    )
    options = run_options(input_path=MINI, chunk_size=2, artifacts_root=tmp_path)
    assert options.plan_id == derived


def test_deriving_with_different_chunking_yields_a_different_plan(
    tmp_path: Path,
) -> None:
    assert derive_plan_id(
        plan_options(input_path=MINI, artifacts_root=tmp_path, chunk_size=2)
    ) != derive_plan_id(
        plan_options(input_path=MINI, artifacts_root=tmp_path, chunk_size=3)
    )


def test_a_limit_participates_in_the_derived_plan_id(tmp_path: Path) -> None:
    assert derive_plan_id(
        plan_options(input_path=MINI, artifacts_root=tmp_path, chunk_size=2, limit=2)
    ) != derive_plan_id(
        plan_options(input_path=MINI, artifacts_root=tmp_path, chunk_size=2)
    )


def test_no_plan_reference_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="plan reference is required"):
        run_options(artifacts_root=Path("/tmp"))


def test_a_copied_bundle_supplies_its_own_plan_id(tmp_path: Path) -> None:
    cohort = resolve_cohort(plan_options(input_path=MINI, artifacts_root=tmp_path))
    plan = build_plan(
        cohort.roster,
        chunk_size=2,
        input_name=cohort.input_name,
        input_fingerprint=cohort.input_fingerprint,
    )
    source = resolve_run_paths(plan.plan_id, tmp_path / "artifacts")
    write_plan(plan, source)

    bundle = tmp_path / "worker-00"
    bundle.mkdir(parents=True)
    shutil.copy2(source.plan_file, bundle / "plan.json")

    assert read_bundle_plan_id(bundle) == plan.plan_id
    assert run_options(bundle_root=str(bundle)).plan_id == plan.plan_id


def test_a_bundle_without_a_manifest_names_nothing(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert read_bundle_plan_id(tmp_path / "empty") == ""
    assert read_bundle_plan_id(tmp_path / "absent") == ""


def test_a_malformed_bundle_manifest_names_nothing(tmp_path: Path) -> None:
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "plan.json").write_text("{not json", encoding="utf-8")
    assert read_bundle_plan_id(tmp_path / "broken") == ""


def test_chunk_selections_accept_ids_or_ranges(tmp_path: Path) -> None:
    assert run_options(plan_id="p", chunk_ids="0-2,5").chunk_ids == (0, 1, 2, 5)
    assert run_options(plan_id="p", chunk_ids=[3, 1]).chunk_ids == (3, 1)
    assert run_options(plan_id="p").chunk_ids == ()


def test_a_worker_count_is_optional_and_defaults_to_unset(tmp_path: Path) -> None:
    assert run_options(plan_id="p").workers is None
    assert run_options(plan_id="p", workers=4).workers == 4


def test_run_paths_point_at_the_bundle_when_one_is_given(tmp_path: Path) -> None:
    options = run_options(plan_id="p", bundle_root=str(tmp_path / "b"))
    paths = options.run_paths()
    assert isinstance(paths, BundleRunPaths)
    assert paths.bundle_root == (tmp_path / "b").resolve()
    assert options.artifacts_root is None


def test_run_paths_point_at_the_coordinator_by_default(tmp_path: Path) -> None:
    options = run_options(plan_id="p", artifacts_root=str(tmp_path))
    paths = options.run_paths()
    assert paths.plan_id == "p"
    assert paths.metadata.artifacts_root == tmp_path.resolve()


# -------------------------------------------------------------- augment options


def test_augment_options_bind_the_parent_snapshot() -> None:
    _options, lineage = augment_options(
        input_path=MINI, base_snapshot_id="base", new_snapshot_id="next"
    )
    assert lineage["parent_snapshot_id"] == "base"


def test_augment_options_resolve_the_chunk_size(monkeypatch) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "9")
    options, _ = augment_options(
        input_path=MINI, base_snapshot_id="b", new_snapshot_id="n"
    )
    assert options.chunk_size == 9
