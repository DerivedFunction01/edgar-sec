from __future__ import annotations

import hashlib
import io
import json

from edgar_sec.pipelines.document_acquisition.fixture_store.capture import (
    create_fixture as _create_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import FixturePlanPin
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    append_fixture_case,
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


def append_test_case(
    paths,
    fixture_id: str,
    target_id: str,
    body: bytes,
    *,
    capture_id: str = "capture-1",
    run_id: str = "run-1",
    attempt_id: str | None = None,
    pin: FixturePlanPin = FIXTURE_PLAN_PIN,
    max_body_bytes: int | None = None,
):
    capture = {
        "capture_id": capture_id,
        "run_id": run_id,
        "target_plan_id": pin.target_plan_id,
        "target_plan_digest": pin.target_plan_digest,
        "target_plan_schema_version": pin.target_plan_schema_version,
        "captured_at_utc": "2026-10-14T00:00:00Z",
    }
    case = {
        "capture_id": capture_id,
        "target_id": target_id,
        "attempt_id": attempt_id or f"attempt-{target_id}",
        "accession": "0000123456-24-000001",
        "form": "4",
        "request_id": f"request-{target_id}",
        "target_role": "primary",
        "target_type": "primary",
        "source_origin": "inventory_index",
        "retrieval_mode": "direct_url",
        "target_url": "https://www.sec.gov/Archives/edgar/data/123456/form4.htm",
        "sequence": None,
        "selected_filename": "form4.htm",
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "byte_size": len(body),
    }
    return append_fixture_case(
        paths,
        fixture_id,
        capture,
        case,
        io.BytesIO(body),
        max_body_bytes=len(body) if max_body_bytes is None else max_body_bytes,
    )
