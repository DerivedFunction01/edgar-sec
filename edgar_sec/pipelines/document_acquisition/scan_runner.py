"""Acquire one bundle_scan target by selecting its document inside the bundle."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.document.unpacking.streaming import (
    BundleExtraction,
    extract_bundle_document_by_type,
)
from edgar_sec.infra.sec_http.streaming import StreamFailure
from edgar_sec.pipelines.document_acquisition.attempts import (
    build_attempt as _attempt,
    relative_path as _relative,
)
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    AcquisitionPolicy,
    AcquisitionStatus,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.resolution import (
    build_scan_resolution,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import TargetState
from edgar_sec.pipelines.document_acquisition.runner_support import (
    AcquisitionTransport,
    new_staging_path as _new_path,
    outcome as _outcome,
    stream as _stream,
    utc_now as _utc,
)


def acquire_scan_target(
    row: dict[str, object],
    state: TargetState,
    *,
    run_id: str,
    run_root: Path,
    staging_root: Path,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
    clock: Callable[[], datetime],
) -> tuple[
    tuple[AcquisitionAttempt, ...],
    AcquisitionOutcome,
    TargetSlotResolution | None,
    str | None,
]:
    accession = AccessionNumber(str(row["accession"]))
    requested_url = row["target_url"]
    if not isinstance(requested_url, str):
        raise ValueError("executable work-order row has no target URL")
    retain_evidence = (
        policy.retain_response_evidence and row["target_role"] == "primary"
    )
    source_path = _new_path(staging_root, "response")
    started = _utc(clock)
    response = _stream(transport, requested_url, source_path, accession, policy)
    finished = _utc(clock)
    number = state.attempt_count + 1
    if isinstance(response, StreamFailure):
        attempt = _attempt(
            target_id=state.target_id,
            number=number,
            kind="document_body",
            requested_url=requested_url,
            result=response,
            started_at_utc=started,
            finished_at_utc=finished,
            source_path=None,
            selected_path=None,
            run_root=run_root,
        )
        return (
            (attempt,),
            _outcome(state.target_id, (attempt,), "failed", error_code=response.code),
            None,
            None,
        )

    selected_path = _new_path(staging_root, "selected")
    extracted = extract_bundle_document_by_type(
        response.path,
        str(row["form"]),
        selected_path,
        expected_source_sha256=response.sha256,
    )
    if isinstance(extracted, BundleExtraction):
        attempt = _attempt(
            target_id=state.target_id,
            number=number,
            kind="document_body",
            requested_url=requested_url,
            result=response,
            started_at_utc=started,
            finished_at_utc=finished,
            source_path=response.path if retain_evidence else None,
            selected_path=selected_path,
            run_root=run_root,
            selected_filename=extracted.selected.filename,
        )
        if not retain_evidence:
            response.path.unlink(missing_ok=True)
        outcome = _outcome(
            state.target_id,
            (attempt,),
            "acquired",
            source_sha256=response.sha256,
            source_byte_size=response.byte_size,
            selected_sha256=extracted.body_sha256,
            selected_byte_size=extracted.body_size,
            selected_path=_relative(run_root, selected_path),
        )
        resolution = build_scan_resolution(
            row | {"run_id": run_id},
            response,
            result="selected_in_bundle",
            selected_sequence=extracted.selected.sequence,
            selected_url=requested_url,
            screen_result="form_match",
            observed_body_type=extracted.selected.document_type,
        )
        return (attempt,), outcome, resolution, _utc(clock)

    if not retain_evidence:
        response.path.unlink(missing_ok=True)
    selected_path.unlink(missing_ok=True)
    if extracted.code == "duplicate_document_type":
        status: AcquisitionStatus = "ambiguous"
        screen_result = "form_match"
    elif extracted.code == "document_type_not_found":
        status = "not_filed" if row["optional"] else "required_missing"
        screen_result = "type_mismatch"
    else:
        status = "failed"
        screen_result = "unverifiable"
    attempt = _attempt(
        target_id=state.target_id,
        number=number,
        kind="document_body",
        requested_url=requested_url,
        result=response,
        started_at_utc=started,
        finished_at_utc=finished,
        source_path=response.path if retain_evidence else None,
        selected_path=None,
        run_root=run_root,
        outcome=status,
        error_code=extracted.code if status == "failed" else None,
    )
    resolution = build_scan_resolution(
        row | {"run_id": run_id},
        response,
        result=status,
        screen_result=screen_result,
    )
    return (
        (attempt,),
        _outcome(
            state.target_id,
            (attempt,),
            status,
            error_code=extracted.code if status == "failed" else None,
        ),
        resolution,
        _utc(clock),
    )


__all__ = ["acquire_scan_target"]
