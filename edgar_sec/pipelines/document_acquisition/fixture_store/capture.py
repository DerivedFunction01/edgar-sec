from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.pipelines.document_acquisition.body_handoff import (
    BodyHandoffError,
    get_staged_body_ref,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureOperationError,
    FixturePlanPin,
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import (
    fixture_plan_pin,
    open_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    append_fixture_case,
    initialize_fixture,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_work_order_rows,
    load_validated_work_order,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import get_target_state


@dataclass(frozen=True, slots=True)
class FixtureRunCaptureResult:
    fixture_id: str
    capture_id: str
    run_id: str
    captured_cases: int
    skipped_targets: int


def create_fixture(
    fixture_id: str, plan_pin: FixturePlanPin, *, paths: AcquisitionPaths
) -> Path:
    try:
        return initialize_fixture(paths, fixture_id, plan_pin).root
    except (FixtureStoreError, OSError, ValueError) as error:
        raise FixtureOperationError(str(error)) from error


def _capture_manifest(paths: AcquisitionPaths, run_id: str) -> dict[str, object]:
    manifest_path = paths.run_manifest_path(run_id)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise FixtureOperationError("run manifest is missing or unsafe")
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise FixtureOperationError("run manifest is unreadable") from error
    if not isinstance(manifest, dict) or canonical_json(manifest) != raw:
        raise FixtureOperationError("run manifest is not canonical JSON")
    digest = manifest.get("run_digest")
    unsigned = dict(manifest)
    unsigned.pop("run_digest", None)
    if (
        manifest.get("run_id") != run_id
        or not is_sha256_hex_digest(digest)
        or canonical_hash(unsigned) != digest
    ):
        raise FixtureOperationError("run manifest identity or digest is invalid")
    if (
        not isinstance(manifest.get("target_plan_id"), str)
        or not manifest["target_plan_id"]
        or not is_sha256_hex_digest(manifest.get("target_plan_digest"))
        or not isinstance(manifest.get("target_schema_version"), int)
        or isinstance(manifest["target_schema_version"], bool)
        or manifest["target_schema_version"] < 1
    ):
        raise FixtureOperationError("run target-plan pin is invalid")
    return manifest


def _capture_timestamp(
    paths: AcquisitionPaths, fixture_id: str, capture_id: str
) -> str:
    _, connection = open_fixture(paths, fixture_id, readonly=True)
    try:
        row = connection.execute(
            "SELECT captured_at_utc FROM captures WHERE capture_id = ?",
            (capture_id,),
        ).fetchone()
        return (
            row[0]
            if row is not None
            else datetime.now(UTC).isoformat(timespec="microseconds")
        )
    finally:
        connection.close()


def capture_fixture_run(
    fixture_id: str,
    run_id: str,
    *,
    paths: AcquisitionPaths,
    max_body_bytes: int,
    on_target: Callable[[int, int], None] | None = None,
) -> FixtureRunCaptureResult:
    if (
        isinstance(max_body_bytes, bool)
        or not isinstance(max_body_bytes, int)
        or max_body_bytes < 1
    ):
        raise FixtureOperationError("max_body_bytes must be positive")
    pin = fixture_plan_pin(paths, fixture_id)
    manifest = _capture_manifest(paths, run_id)
    if (
        manifest["target_plan_id"] != pin.target_plan_id
        or manifest["target_plan_digest"] != pin.target_plan_digest
        or manifest["target_schema_version"] != pin.target_plan_schema_version
    ):
        raise FixtureOperationError("acquisition run differs from fixture plan pin")

    rows = tuple(iter_work_order_rows(load_validated_work_order(paths, run_id)))
    selected = []
    skipped = 0
    for index, row in enumerate(rows, start=1):
        if on_target is not None:
            on_target(index, len(rows))
        if not row["executable"]:
            skipped += 1
            continue
        target_id = str(row["target_id"])
        state = get_target_state(paths.run_state_path(run_id), target_id)
        if (
            state is None
            or state.outcome != "acquired"
            or state.last_attempt_id is None
        ):
            skipped += 1
            continue
        try:
            body = get_staged_body_ref(paths, run_id, target_id, verify_source=False)
        except (BodyHandoffError, OSError) as error:
            raise FixtureOperationError(
                f"selected body for target {target_id} is unavailable: {error}"
            ) from error
        if body.byte_size > max_body_bytes:
            raise FixtureOperationError(
                f"selected body for target {target_id} exceeds max_body_bytes"
            )
        selected.append((row, state, body))

    if not selected:
        raise FixtureOperationError(
            "run has no acquired targets with selected staged bodies"
        )
    capture_id = (
        "cap_"
        + canonical_hash(
            {
                "run_id": run_id,
                "targets": sorted(
                    (
                        str(row["target_id"]),
                        state.last_attempt_id,
                        body.sha256,
                    )
                    for row, state, body in selected
                ),
            }
        )[:32]
    )
    capture = {
        "capture_id": capture_id,
        "run_id": run_id,
        "target_plan_id": pin.target_plan_id,
        "target_plan_digest": pin.target_plan_digest,
        "target_plan_schema_version": pin.target_plan_schema_version,
        "captured_at_utc": _capture_timestamp(paths, fixture_id, capture_id),
    }
    for row, state, body in selected:
        target_id = str(row["target_id"])
        selected_filename = (
            body.selected_filename
            or urlsplit(str(row["target_url"] or "")).path.rsplit("/", 1)[-1]
        )
        if not selected_filename:
            raise FixtureOperationError(
                f"selected body for target {target_id} has no document filename"
            )
        case = {
            "capture_id": capture_id,
            "target_id": target_id,
            "attempt_id": state.last_attempt_id,
            "accession": str(row["accession"]),
            "form": str(row["form"]),
            "request_id": str(row["request_id"]),
            "target_role": str(row["target_role"]),
            "target_type": str(row["target_type"]),
            "source_origin": str(row["source_origin"]),
            "retrieval_mode": str(row["retrieval_mode"]),
            "target_url": row["target_url"],
            "sequence": (
                int(row["sequence"])
                if row["retrieval_mode"] == "bundle_sequence"
                and row["sequence"] is not None
                else None
            ),
            "selected_filename": selected_filename,
            "body_sha256": body.sha256,
            "byte_size": body.byte_size,
        }
        with body.path.open("rb") as source:
            append_fixture_case(
                paths,
                fixture_id,
                capture,
                case,
                source,
                max_body_bytes=max_body_bytes,
            )
    return FixtureRunCaptureResult(
        fixture_id=fixture_id,
        capture_id=capture_id,
        run_id=run_id,
        captured_cases=len(selected),
        skipped_targets=skipped,
    )
