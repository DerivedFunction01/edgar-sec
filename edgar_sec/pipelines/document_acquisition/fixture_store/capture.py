from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.engine.document.unpacking.streaming import (
    BundleExtraction,
    extract_bundle_sequence,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    get_fixture_case,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixturePlanPin,
    FixtureOperationError,
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    append_fixture_case,
    initialize_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import (
    fixture_plan_pin,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.run_state.evidence import (
    AttemptEvidenceGroup,
    get_attempt_evidence_group,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    get_target_state,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_work_order_rows,
    load_validated_work_order,
)


@dataclass(frozen=True, slots=True)
class FixtureCaptureResult:
    fixture_id: str
    capture_id: str
    run_id: str
    target_id: str
    attempt_id: str
    acquisition_status: str
    response_sha256: str | None
    source_byte_size: int | None
    reused_response: bool


def create_fixture(
    fixture_id: str, plan_pin: FixturePlanPin, *, paths: AcquisitionPaths
) -> Path:
    try:
        return initialize_fixture(paths, fixture_id, plan_pin).root
    except (FixtureStoreError, OSError, ValueError) as error:
        raise FixtureOperationError(str(error)) from error


def _find_target(parts: tuple[Path, ...], target_id: str) -> dict[str, object]:
    found = None
    for row in iter_work_order_rows(parts):
        if row["target_id"] == target_id:
            if found is not None:
                raise FixtureOperationError("target ID is duplicated in work order")
            found = row
    if found is None:
        raise FixtureOperationError("target ID is not in the run work order")
    return found


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
        raise FixtureOperationError("run manifest target-plan provenance is invalid")
    snapshot_id = manifest.get("inventory_snapshot_id")
    snapshot_digest = manifest.get("inventory_snapshot_digest")
    if (
        (snapshot_id is None) != (snapshot_digest is None)
        or (
            snapshot_id is not None
            and (not isinstance(snapshot_id, str) or not snapshot_id.strip())
        )
        or (snapshot_digest is not None and not is_sha256_hex_digest(snapshot_digest))
    ):
        raise FixtureOperationError("run manifest inventory provenance is invalid")
    return manifest


def _body_path(
    paths: AcquisitionPaths, run_id: str, relative_path: str, size: int
) -> Path:
    relative = PurePosixPath(relative_path)
    run_root = paths.run_dir(run_id)
    staging_root = paths.run_staging_root(run_id)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "\\" in relative_path
        or run_root.is_symlink()
        or staging_root.is_symlink()
        or not staging_root.is_dir()
    ):
        raise FixtureOperationError("attempt body path is unsafe")
    candidate = run_root.joinpath(*relative.parts)
    current = run_root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise FixtureOperationError("attempt body path contains a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(staging_root.resolve(strict=True)):
            raise FixtureOperationError("attempt body path escapes run staging")
        descriptor = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise FixtureOperationError("attempt body file is missing or unsafe") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
            raise FixtureOperationError("attempt body size or type is invalid")
    finally:
        os.close(descriptor)
    return resolved


def _body_stream(path: Path, expected_size: int):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_size != expected_size:
        os.close(descriptor)
        raise FixtureOperationError("attempt body changed after validation")
    return os.fdopen(descriptor, "rb")


def _attempt_response_path(
    paths: AcquisitionPaths, run_id: str, attempt, *, selected: bool = False
) -> Path | None:
    digest = attempt.selected_sha256 if selected else attempt.source_sha256
    size = attempt.selected_byte_size if selected else attempt.source_byte_size
    relative_path = (
        attempt.selected_body_relative_path
        if selected
        else attempt.source_body_relative_path
    )
    if digest is None and size is None and relative_path is None:
        return None
    if (
        not is_sha256_hex_digest(digest)
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 0
        or relative_path is None
    ):
        raise FixtureOperationError("response evidence is incomplete or not retained")
    path = _body_path(paths, run_id, relative_path, size)
    if file_sha256(path) != digest:
        raise FixtureOperationError("response_sha256 does not match attempt evidence")
    return path


def _capture_resolution_fields(resolution) -> dict[str, object]:
    if resolution is None:
        return dict.fromkeys(
            "index_response_sha256 selected_response_sha256 resolution_schema_version "
            "screen_kind screen_result evaluator_version index_parser_version "
            "matching_entry_ids_json selected_sequence selected_retrieval_mode "
            "selected_url".split()
        )
    return {
        "index_response_sha256": resolution.index_response_sha256,
        "selected_response_sha256": None,
        "resolution_schema_version": resolution.resolution_schema_version,
        "screen_kind": resolution.screen_kind,
        "screen_result": resolution.screen_result,
        "evaluator_version": resolution.evaluator_version,
        "index_parser_version": resolution.index_parser_version,
        "matching_entry_ids_json": canonical_json(list(resolution.matching_entry_ids)),
        "selected_sequence": resolution.selected_sequence,
        "selected_retrieval_mode": resolution.selected_retrieval_mode,
        "selected_url": resolution.selected_url,
    }


def capture_fixture_case(
    fixture_id: str,
    run_id: str,
    target_id: str,
    attempt_id: str,
    *,
    paths: AcquisitionPaths,
    max_response_bytes: int,
) -> FixtureCaptureResult:
    if (
        isinstance(max_response_bytes, bool)
        or not isinstance(max_response_bytes, int)
        or max_response_bytes < 1
    ):
        raise FixtureOperationError("max_response_bytes must be positive")
    plan_pin = fixture_plan_pin(paths, fixture_id)
    manifest = _capture_manifest(paths, run_id)
    if (
        manifest["target_plan_id"] != plan_pin.target_plan_id
        or manifest["target_plan_digest"] != plan_pin.target_plan_digest
        or manifest["target_schema_version"] != plan_pin.target_plan_schema_version
    ):
        raise FixtureOperationError("acquisition run differs from fixture plan pin")
    parts = load_validated_work_order(paths, run_id)
    row = _find_target(parts, target_id)
    try:
        group: AttemptEvidenceGroup | None = get_attempt_evidence_group(
            paths.run_state_path(run_id), target_id, attempt_id
        )
    except (OSError, ValueError) as error:
        raise FixtureOperationError(str(error)) from error
    if group is None:
        raise FixtureOperationError("attempt ID is not recorded for this target")
    attempt = group.initial_attempt
    if attempt.attempt_kind != "document_body" or attempt.source != "live_sec":
        raise FixtureOperationError("only live document-body attempts can be captured")
    state = get_target_state(paths.run_state_path(run_id), target_id)
    latest_attempt = group.selected_body_attempt or group.lazy_index_attempt or attempt
    if state is None or state.last_attempt_id != latest_attempt.attempt_id:
        raise FixtureOperationError("attempt is not the latest target attempt")
    bodyless_failure = (
        state.outcome == "failed"
        and all(
            value is None
            for value in (
                attempt.source_sha256,
                attempt.source_byte_size,
                attempt.source_body_relative_path,
                attempt.selected_sha256,
                attempt.selected_byte_size,
                attempt.selected_body_relative_path,
            )
        )
        and group.lazy_index_attempt is None
    )

    source_path = _attempt_response_path(paths, run_id, attempt)
    if attempt.outcome == "acquired" and source_path is None:
        raise FixtureOperationError("source response body was not retained")
    initial_selected_path = _attempt_response_path(
        paths, run_id, attempt, selected=True
    )
    index_path = None
    if group.lazy_index_attempt is not None:
        index_path = _attempt_response_path(paths, run_id, group.lazy_index_attempt)
        if group.lazy_index_attempt.outcome == "acquired" and index_path is None:
            raise FixtureOperationError("lazy-index response was not retained")
    selected_response_path = None
    selected_child_path = None
    if group.selected_body_attempt is not None:
        selected_response_path = _attempt_response_path(
            paths, run_id, group.selected_body_attempt
        )
        if (
            group.selected_body_attempt.outcome == "acquired"
            and selected_response_path is None
        ):
            raise FixtureOperationError("selected response was not retained")
        selected_child_path = _attempt_response_path(
            paths, run_id, group.selected_body_attempt, selected=True
        )

    resolution = group.resolution
    if resolution is not None:
        if resolution.index_attempt_id != getattr(
            group.lazy_index_attempt, "attempt_id", None
        ) or resolution.index_response_sha256 != getattr(
            group.lazy_index_attempt, "source_sha256", None
        ):
            raise FixtureOperationError(
                "lazy-index response differs from resolution evidence"
            )
        if resolution.index_response_sha256 is not None and index_path is None:
            raise FixtureOperationError("lazy-index response evidence was not retained")
        if resolution.selected_url is not None and group.selected_body_attempt is None:
            raise FixtureOperationError("selected response attempt is missing")
        if group.selected_body_attempt is not None:
            if group.selected_body_attempt.requested_url != resolution.selected_url:
                raise FixtureOperationError(
                    "selected response URL differs from resolution"
                )
            if (
                group.selected_body_attempt.source_sha256 is not None
                and selected_response_path is None
            ):
                raise FixtureOperationError(
                    "selected response evidence was not retained"
                )

    selected_filename: str | None = None
    if state.outcome == "acquired":
        if source_path is None or attempt.source_sha256 is None:
            raise FixtureOperationError("source response body was not retained")
        if state.selected_sha256 is None or state.selected_byte_size is None:
            raise FixtureOperationError(
                "acquired target has incomplete selected identity"
            )
        if resolution is not None:
            selected_attempt = group.selected_body_attempt
            if selected_attempt is None or selected_response_path is None:
                raise FixtureOperationError(
                    "selected response evidence was not retained"
                )
            if resolution.selected_retrieval_mode == "direct_url":
                if (
                    selected_attempt.source_sha256 != state.selected_sha256
                    or selected_attempt.source_byte_size != state.selected_byte_size
                    or selected_attempt.selected_sha256 != state.selected_sha256
                    or selected_attempt.selected_byte_size != state.selected_byte_size
                    or selected_child_path is None
                ):
                    raise FixtureOperationError(
                        "selected response differs from selected body"
                    )
                selected_filename = urlsplit(str(resolution.selected_url)).path.rsplit(
                    "/", 1
                )[-1]
            elif resolution.selected_retrieval_mode == "bundle_sequence":
                if resolution.selected_sequence is None:
                    raise FixtureOperationError("selected bundle sequence is missing")
                with tempfile.TemporaryDirectory(prefix="acq-capture-verify-") as root:
                    extracted = extract_bundle_sequence(
                        selected_response_path,
                        resolution.selected_sequence,
                        Path(root) / "selected-body.bin",
                        expected_source_sha256=selected_attempt.source_sha256,
                    )
                if (
                    not isinstance(extracted, BundleExtraction)
                    or extracted.body_sha256 != state.selected_sha256
                    or extracted.body_size != state.selected_byte_size
                ):
                    code = (
                        extracted.code
                        if not isinstance(extracted, BundleExtraction)
                        else "source_mismatch"
                    )
                    raise FixtureOperationError(
                        f"selected bundle response differs from selected-body evidence: {code}"
                    )
                selected_filename = extracted.selected.filename or (
                    f"sequence-{resolution.selected_sequence}"
                )
            else:
                raise FixtureOperationError("resolution has no selected retrieval mode")
        elif row["retrieval_mode"] == "direct_url":
            selected_path = initial_selected_path
            if selected_path is None:
                if (
                    attempt.source_sha256 == state.selected_sha256
                    and attempt.source_byte_size == state.selected_byte_size
                ):
                    selected_path = source_path
                else:
                    raise FixtureOperationError("selected body path is missing")
            if (
                attempt.source_sha256 != state.selected_sha256
                or attempt.source_byte_size != state.selected_byte_size
                or attempt.selected_sha256 != state.selected_sha256
                or attempt.selected_byte_size != state.selected_byte_size
            ):
                raise FixtureOperationError("direct response and selected body differ")
            selected_filename = urlsplit(
                attempt.final_url or str(row["target_url"])
            ).path.rsplit("/", 1)[-1]
        else:
            if source_path is None or initial_selected_path is None:
                raise FixtureOperationError("bundle response evidence was not retained")
            if (
                attempt.selected_sha256 != state.selected_sha256
                or attempt.selected_byte_size != state.selected_byte_size
            ):
                raise FixtureOperationError(
                    "bundle selected-body evidence differs from run state"
                )
            with tempfile.TemporaryDirectory(prefix="acq-capture-verify-") as root:
                extracted = extract_bundle_sequence(
                    source_path,
                    int(row["sequence"]),
                    Path(root) / "selected-body.bin",
                    expected_source_sha256=attempt.source_sha256,
                )
            if (
                not isinstance(extracted, BundleExtraction)
                or extracted.body_sha256 != state.selected_sha256
                or extracted.body_size != state.selected_byte_size
            ):
                code = (
                    extracted.code
                    if not isinstance(extracted, BundleExtraction)
                    else "source_mismatch"
                )
                raise FixtureOperationError(
                    f"bundle source differs from selected-body evidence: {code}"
                )
            selected_filename = (
                extracted.selected.filename or f"sequence-{row['sequence']}"
            )
        if not selected_filename:
            raise FixtureOperationError("acquired response has no selected filename")
    elif (
        not bodyless_failure
        and source_path is None
        and index_path is None
        and selected_response_path is None
    ):
        raise FixtureOperationError("failed capture has no retained response evidence")
    if (
        row["catalog_direct_selection"] == "exact_form_with_lazy_index"
        and not bodyless_failure
        and resolution is None
    ):
        raise FixtureOperationError(
            "lazy-index capture requires the initial document-body attempt"
        )

    capture_id = (
        "cap_"
        + canonical_hash(
            {"run_id": run_id, "target_id": target_id, "attempt_id": attempt_id}
        )[:32]
    )
    try:
        existing_case = get_fixture_case(paths, fixture_id, capture_id, target_id)
    except FixtureStoreError as error:
        if str(error) != "fixture case not found":
            raise FixtureOperationError(str(error)) from error
        captured_at = datetime.now(UTC).isoformat(timespec="microseconds")
    else:
        captured_at = existing_case.captured_at_utc
    capture = {
        "capture_id": capture_id,
        "run_id": run_id,
        "target_plan_id": manifest["target_plan_id"],
        "target_plan_digest": manifest["target_plan_digest"],
        "target_plan_schema_version": str(manifest["target_schema_version"]),
        "inventory_snapshot_id": manifest["inventory_snapshot_id"],
        "inventory_snapshot_digest": manifest["inventory_snapshot_digest"],
        "captured_at_utc": captured_at,
    }
    case = {
        "target_id": target_id,
        "attempt_id": attempt_id,
        "accession": row["accession"],
        "form": row["form"],
        "request_id": row["request_id"],
        "target_role": row["target_role"],
        "target_type": row["target_type"],
        "optional": int(bool(row["optional"])),
        "catalog_direct_selection": row["catalog_direct_selection"],
        "source_origin": row["source_origin"],
        "target_status": row["status"],
        "retrieval_mode": row["retrieval_mode"],
        "target_url": row["target_url"],
        "final_url": attempt.final_url,
        "sequence": row["sequence"]
        if row["retrieval_mode"] == "bundle_sequence"
        else None,
        "acquisition_status": state.outcome,
        "error_code": state.error_code,
        "response_sha256": attempt.source_sha256,
        **_capture_resolution_fields(resolution),
        "selected_response_sha256": (
            group.selected_body_attempt.source_sha256
            if resolution is not None and group.selected_body_attempt is not None
            else None
        ),
        "source_byte_size": attempt.source_byte_size,
        "selected_sha256": state.selected_sha256
        if state.outcome == "acquired"
        else None,
        "selected_byte_size": state.selected_byte_size
        if state.outcome == "acquired"
        else None,
        "selected_filename": selected_filename,
        "content_type": None,
        "content_encoding": None,
    }
    try:
        with ExitStack() as stack:
            body_source = (
                stack.enter_context(_body_stream(source_path, attempt.source_byte_size))
                if source_path is not None and attempt.source_byte_size is not None
                else None
            )
            related_responses = {}
            if (
                index_path is not None
                and group.lazy_index_attempt.source_byte_size is not None
            ):
                related_responses["index_response_sha256"] = stack.enter_context(
                    _body_stream(index_path, group.lazy_index_attempt.source_byte_size)
                )
            if (
                selected_response_path is not None
                and group.selected_body_attempt.source_byte_size is not None
            ):
                related_responses["selected_response_sha256"] = stack.enter_context(
                    _body_stream(
                        selected_response_path,
                        group.selected_body_attempt.source_byte_size,
                    )
                )
            body_ref = append_fixture_case(
                paths,
                fixture_id,
                capture,
                case,
                body_source,
                max_response_bytes=max_response_bytes,
                related_responses=related_responses,
            )
    except FixtureStoreError as error:
        raise FixtureOperationError(str(error)) from error
    return FixtureCaptureResult(
        fixture_id,
        capture_id,
        run_id,
        target_id,
        attempt_id,
        state.outcome,
        body_ref.response_sha256 if body_ref else None,
        body_ref.byte_size if body_ref else None,
        body_ref.reused if body_ref else False,
    )
