"""Fixtures needed by more than one test package; the rest live in their package."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.settings.paths import DEFAULT_ARTIFACTS_ROOT
from tests.support import catalog_fixture_path

SAMPLE_SUBMISSION_METADATA = "sample_submission_metadata.parquet"


@pytest.fixture
def sample_source() -> Path:
    """Consumed by the catalog pipeline and the company-family engine tests."""
    return catalog_fixture_path(SAMPLE_SUBMISSION_METADATA)


@pytest.fixture(scope="session", autouse=True)
def regenerable_fixtures_seeded() -> None:
    """Seed regenerated fixture data when any of it is absent (fresh clone).

    Archive slices and catalog outputs are untracked regenerated data.
    """
    import fcntl

    from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
    from edgar_sec.tools.xbrl_discovery.build_taxonomy_archive import (
        _releases,
        build,
    )

    # The cache dir mirrors the builder CLI's --cache-dir default.
    cache_dir = Path.home() / "workspace" / "xbrl-triage" / "taxonomy-archive-src"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # One worker seeds while the rest wait: concurrent builds rewrite
    # the same slices under each other's readers (torn parquet reads).
    with open(cache_dir / ".seed.lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        archive_dir = resolve_xbrl_paths().default_taxonomy_archive_dir
        missing = [
            (taxonomy, version)
            for taxonomy, version, _url in _releases()
            if not (archive_dir / taxonomy / f"{version}.parquet").is_file()
        ]
        if missing:
            build(cache_dir, archive_dir)
        _seed_catalog_fixtures()


def _seed_catalog_fixtures() -> None:
    import importlib.util
    import json

    fixtures_dir = Path(__file__).resolve().parent / "fixtures" / "catalog"
    expected = [
        fixtures_dir / "cohort_observations.json.sha256",
        fixtures_dir / "cohort_observations_plan_fixture.sha256",
        fixtures_dir / "s1_plan" / "plan.json",
    ]
    cohort_manifest = fixtures_dir / "cohort_observations.json.sha256"
    if cohort_manifest.is_file():
        entries = json.loads(cohort_manifest.read_text(encoding="utf-8"))["fixtures"]
        expected += [fixtures_dir / f"{entry['name']}.parquet" for entry in entries]
        plan_manifest = json.loads(
            (fixtures_dir / "cohort_observations_plan_fixture.sha256").read_text(
                encoding="utf-8"
            )
        )
        expected += [
            fixtures_dir / "s1_plan" / "targets" / form / "data.parquet"
            for form in plan_manifest
        ]
    if all(path.is_file() for path in expected):
        return
    spec = importlib.util.spec_from_file_location(
        "_author_cohort_fixtures", fixtures_dir / "_author_cohort_fixtures.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("catalog fixture generator could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


@pytest.fixture(scope="session", autouse=True)
def no_production_artifact_writes() -> Iterator[None]:
    """Fail session if tests write to this repository's own artifacts tree."""
    guarded = ("cohorts", "cache", "document_planning")
    before = {
        sub: (
            {p.name for p in (DEFAULT_ARTIFACTS_ROOT / sub).iterdir()}
            if (DEFAULT_ARTIFACTS_ROOT / sub).is_dir()
            else set()
        )
        for sub in guarded
    }
    yield
    for sub in guarded:
        root = DEFAULT_ARTIFACTS_ROOT / sub
        after = {p.name for p in root.iterdir()} if root.is_dir() else set()
        leaked = sorted(after - before[sub])
        assert not leaked, (
            f"tests wrote production artifacts under {root}: {leaked}. "
            "Pass tmp_path as the artifacts_root when running operations in tests."
        )
