import json

from edgar_sec.pipelines.document_acquisition.fixture_store.capture import (
    create_fixture as _create_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import FixturePlanPin
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    initialize_fixture as _initialize_fixture,
)
from edgar_sec.pipelines.document_planning.paths import resolve_document_planning_paths

FIXTURE_PLAN_PIN = FixturePlanPin("plan_fixture_test", "a" * 64, 1)


def initialize_test_fixture(paths, fixture_id: str):
    return _initialize_fixture(paths, fixture_id, FIXTURE_PLAN_PIN)


def create_test_fixture(paths, fixture_id: str, plan_pin: FixturePlanPin):
    return _create_fixture(fixture_id, plan_pin, paths=paths)


def create_test_fixture_for_run(paths, fixture_id: str, run_id: str):
    return _create_fixture(fixture_id, plan_pin_for_run(paths, run_id), paths=paths)


def plan_pin_for_run(paths, run_id: str) -> FixturePlanPin:
    manifest = json.loads(paths.run_manifest_path(run_id).read_text(encoding="utf-8"))
    return FixturePlanPin(
        manifest["target_plan_id"],
        manifest["target_plan_digest"],
        manifest["target_schema_version"],
    )


def plan_pin_for_published_plan(paths, plan_id: str) -> FixturePlanPin:
    manifest_path = resolve_document_planning_paths(
        artifacts_root=paths.artifacts_root
    ).plan_manifest_path(plan_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return FixturePlanPin(
        plan_id, manifest["plan_digest"], manifest["target_schema_version"]
    )
