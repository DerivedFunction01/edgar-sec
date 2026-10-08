from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.pipelines.metadata_sync.options import (
    BundleRunPaths,
    PlanOptions,
    derive_plan_id,
    plan_options,
    read_bundle_plan_id,
    resolve_chunk_size,
    resolve_cohort,
    run_options,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from tests.pipelines.metadata_sync.cohort_support import publish_test_cohort
from tests.support import fixture_path

MINI = fixture_path("cik_sec_mini.csv")


def _publish(root: Path):
    return publish_test_cohort(MINI, root)


def test_an_explicit_chunk_size_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    record, _paths, _roster = _publish(tmp_path)
    assert (
        plan_options(
            cohort=record.cohort_id, artifacts_root=tmp_path, chunk_size=5
        ).chunk_size
        == 5
    )


def test_the_registry_supplies_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    record, _paths, _roster = _publish(tmp_path)
    assert (
        plan_options(cohort=record.cohort_id, artifacts_root=tmp_path).chunk_size == 7
    )


def test_the_code_default_applies_with_no_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("RUNTIME_CHUNK_SIZE", raising=False)
    record, _paths, _roster = _publish(tmp_path)
    assert (
        plan_options(cohort=record.cohort_id, artifacts_root=tmp_path).chunk_size
        == DEFAULT_CHUNK_SIZE
    )


def test_resolve_chunk_size_is_pure_over_its_argument(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    assert resolve_chunk_size(5) == 5
    assert resolve_chunk_size(None) == 7


def test_plan_options_have_only_the_cohort_dataset_selector():
    assert not hasattr(PlanOptions, "workers")
    assert PlanOptions.__slots__ == ("cohort", "artifacts_root", "chunk_size", "limit")


def test_a_published_cohort_is_required(tmp_path: Path):
    with pytest.raises(ValueError, match="--cohort is required"):
        plan_options(artifacts_root=tmp_path).roster()


def test_published_cohort_identity_and_limit_are_resolved(tmp_path: Path):
    record, _paths, _source_roster = _publish(tmp_path)
    full = resolve_cohort(
        plan_options(cohort=record.cohort_id, artifacts_root=tmp_path)
    )
    limited = resolve_cohort(
        plan_options(cohort=record.cohort_id, artifacts_root=tmp_path, limit=2)
    )
    assert full.input_name == f"cohort:{record.cohort_id}"
    assert full.input_fingerprint == record.dataset_sha256
    assert full.roster.row_count == record.row_count == 4
    assert limited.roster.row_count == 2
    assert limited.roster.roster_id != full.roster.roster_id
    assert limited.input_fingerprint == full.input_fingerprint
    assert limited.roster.dataset is not None
    assert "transient" in limited.roster.dataset.parts


def test_a_limit_must_be_positive(tmp_path: Path):
    record, _paths, _roster = _publish(tmp_path)
    with pytest.raises(ValueError, match="limit"):
        resolve_cohort(
            plan_options(cohort=record.cohort_id, artifacts_root=tmp_path, limit=0)
        )


@pytest.mark.parametrize(
    ("alias", "source"), [("universe", "cik_lookup"), ("tickers", "company_tickers")]
)
def test_active_cohort_aliases_resolve_through_layer_two(
    alias: str, source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from edgar_sec.infra.storage.cohort import sources

    record, _paths, _roster = _publish(tmp_path)
    observed = []

    def resolve_active_source(name, *, catalog):
        observed.append((name, catalog))
        return record

    monkeypatch.setattr(sources, "resolve_active_source", resolve_active_source)
    selected = resolve_cohort(plan_options(cohort=alias, artifacts_root=tmp_path))
    assert selected.input_name == f"cohort:{record.cohort_id}"
    assert observed[0][0] == source


def test_missing_active_alias_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from edgar_sec.infra.storage.cohort import sources

    monkeypatch.setattr(
        sources, "resolve_active_source", lambda *_args, **_kwargs: None
    )
    with pytest.raises(ValueError, match="no active universe cohort"):
        resolve_cohort(plan_options(cohort="universe", artifacts_root=tmp_path))


def test_lineage_uses_the_canonical_cohort_id(tmp_path: Path):
    record, _paths, _roster = _publish(tmp_path)
    selected = resolve_cohort(
        plan_options(cohort=record.cohort_id, artifacts_root=tmp_path)
    )
    assert selected.input_name == f"cohort:{record.cohort_id}"
    assert selected.input_fingerprint == record.dataset_sha256


def test_a_plan_id_can_be_rederived_from_a_cohort(tmp_path: Path):
    record, _paths, _roster = _publish(tmp_path)
    derived = derive_plan_id(
        plan_options(cohort=record.cohort_id, artifacts_root=tmp_path, chunk_size=2)
    )
    options = run_options(
        cohort=record.cohort_id, chunk_size=2, artifacts_root=tmp_path
    )
    assert options.plan_id == derived


def test_deriving_with_different_chunking_yields_a_different_plan(tmp_path: Path):
    record, _paths, _roster = _publish(tmp_path)
    assert derive_plan_id(
        plan_options(cohort=record.cohort_id, artifacts_root=tmp_path, chunk_size=2)
    ) != derive_plan_id(
        plan_options(cohort=record.cohort_id, artifacts_root=tmp_path, chunk_size=3)
    )


def test_a_limit_participates_in_the_derived_plan_id(tmp_path: Path):
    record, _paths, _roster = _publish(tmp_path)
    assert derive_plan_id(
        plan_options(
            cohort=record.cohort_id, artifacts_root=tmp_path, chunk_size=2, limit=2
        )
    ) != derive_plan_id(
        plan_options(cohort=record.cohort_id, artifacts_root=tmp_path, chunk_size=2)
    )


def test_no_plan_reference_is_refused():
    with pytest.raises(ValueError, match="plan reference is required"):
        run_options(artifacts_root=Path("/tmp"))


def test_a_copied_bundle_supplies_its_own_plan_id(tmp_path: Path):
    record, _paths, _roster = _publish(tmp_path)
    cohort = resolve_cohort(
        plan_options(cohort=record.cohort_id, artifacts_root=tmp_path)
    )
    plan = build_plan(
        cohort.roster,
        chunk_size=2,
        input_name=cohort.input_name,
        input_fingerprint=cohort.input_fingerprint,
    )
    source = resolve_run_paths(plan.plan_id, tmp_path / "artifacts")
    write_plan(plan, source)
    bundle = tmp_path / "worker-00"
    bundle.mkdir()
    shutil.copy2(source.plan_file, bundle / "plan.json")
    assert read_bundle_plan_id(bundle) == plan.plan_id
    assert run_options(bundle_root=str(bundle)).plan_id == plan.plan_id


def test_bundle_without_a_manifest_names_nothing(tmp_path: Path):
    (tmp_path / "empty").mkdir()
    assert read_bundle_plan_id(tmp_path / "empty") == ""
    assert read_bundle_plan_id(tmp_path / "absent") == ""


def test_malformed_bundle_manifest_names_nothing(tmp_path: Path):
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "plan.json").write_text("{not json", encoding="utf-8")
    assert read_bundle_plan_id(tmp_path / "broken") == ""


def test_chunk_selections_accept_ids_or_ranges():
    assert run_options(plan_id="p", chunk_ids="0-2,5").chunk_ids == (0, 1, 2, 5)
    assert run_options(plan_id="p", chunk_ids=[3, 1]).chunk_ids == (3, 1)
    assert run_options(plan_id="p").chunk_ids == ()


def test_worker_count_is_optional_and_defaults_to_unset():
    assert run_options(plan_id="p").workers is None
    assert run_options(plan_id="p", workers=4).workers == 4


def test_run_paths_point_at_a_bundle(tmp_path: Path):
    options = run_options(plan_id="p", bundle_root=str(tmp_path / "b"))
    assert isinstance(options.run_paths(), BundleRunPaths)
    assert options.run_paths().bundle_root == (tmp_path / "b").resolve()
    assert options.artifacts_root is None


def test_run_paths_point_at_the_coordinator_by_default(tmp_path: Path):
    options = run_options(plan_id="p", artifacts_root=str(tmp_path))
    assert options.run_paths().plan_id == "p"
    assert options.run_paths().metadata.artifacts_root == tmp_path.resolve()


def test_augmentation_options_use_the_cohort_selector_and_runtime_chunk_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "9")
    record, _paths, _roster = _publish(tmp_path)
    options = plan_options(cohort=record.cohort_id, artifacts_root=tmp_path)
    assert options.cohort == record.cohort_id
    assert options.chunk_size == 9
