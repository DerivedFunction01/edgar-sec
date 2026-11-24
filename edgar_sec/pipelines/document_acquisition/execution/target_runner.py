"""Acquire one validated target with bounded response staging."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.document.screening import screen_candidate_document
from edgar_sec.infra.sec_http.streaming import StreamFailure
from edgar_sec.pipelines.document_acquisition.execution.attempts import (
    build_attempt as _attempt,
)
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    AcquisitionPolicy,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.execution.runner_support import (
    AcquisitionTransport,
    apply_structure_screen as _apply_structure_screen,
    has_lazy_index_trigger as _has_lazy_index_trigger,
    new_staging_path as _new_path,
    outcome as _outcome,
    read_screen_head as _read_screen_head,
    resolution_screen_kind as _resolution_screen_kind,
    stream as _stream,
    utc_now as _utc,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.run_state.models import TargetState
from edgar_sec.pipelines.document_acquisition.execution.scan_runner import (
    acquire_scan_target as _acquire_scan_target,
)
from edgar_sec.pipelines.document_acquisition.execution.bundle_extraction import (
    BundleRecovery,
    extract_bundle_selection,
)
from edgar_sec.pipelines.document_acquisition.execution.direct_runner import (
    acquire_direct_target,
)
from edgar_sec.pipelines.document_acquisition.execution.lazy_runner import (
    acquire_lazy_target,
)


def acquire_target(
    row: dict[str, object],
    state: TargetState,
    *,
    run_id: str,
    paths: AcquisitionPaths,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
    clock: Callable[[], datetime],
) -> tuple[
    tuple[AcquisitionAttempt, ...],
    AcquisitionOutcome,
    TargetSlotResolution | None,
    str | None,
]:
    run_root = paths.run_dir(run_id)
    staging_root = paths.run_staging_root(run_id)
    if staging_root.is_symlink():
        raise ValueError("run staging directory is unsafe")
    staging_root.mkdir(parents=True, exist_ok=True)
    if not staging_root.resolve().is_relative_to(run_root.resolve()):
        raise ValueError("run staging directory escapes its run")
    accession = AccessionNumber(str(row["accession"]))
    requested_url = row["target_url"]
    if not isinstance(requested_url, str):
        raise ValueError("executable work-order row has no target URL")
    if row["retrieval_mode"] == "bundle_scan":
        return _acquire_scan_target(
            row,
            state,
            run_id=run_id,
            run_root=run_root,
            staging_root=staging_root,
            policy=policy,
            transport=transport,
            clock=clock,
        )
    retain_evidence = (
        policy.retain_response_evidence
        and row["target_role"] == "primary"
        and (row["retrieval_mode"] == "bundle_sequence" or _has_lazy_index_trigger(row))
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

    sgml_recovery = False
    fallback_selected_path = source_path
    fallback_selected_filename: str | None = None
    screen_context: dict[str, str | None] = {
        "screen_kind": "html_cover",
        "screen_result": "unverifiable",
        "observed_body_type": None,
    }
    if row["retrieval_mode"] == "bundle_sequence":
        bundle_result = extract_bundle_selection(
            row,
            state,
            response=response,
            staging_root=staging_root,
            run_root=run_root,
            number=number,
            requested_url=requested_url,
            started=started,
            finished=finished,
            retain_evidence=retain_evidence,
            fallback_selected_path=fallback_selected_path,
            fallback_selected_filename=fallback_selected_filename,
            screen_context=screen_context,
        )
        if not isinstance(bundle_result, BundleRecovery):
            return bundle_result
        sgml_recovery = True
        fallback_selected_path = bundle_result.fallback_selected_path
        fallback_selected_filename = bundle_result.fallback_selected_filename
        screen_context = bundle_result.screen_context

    direct_screen_recovery = False
    if (
        row["retrieval_mode"] == "direct_url"
        and _has_lazy_index_trigger(row)
        and row["sequence"] == 1
    ):
        head = _read_screen_head(source_path)
        screen = _apply_structure_screen(
            screen_candidate_document(
                str(row["form"]),
                filename=urlsplit(requested_url).path.rsplit("/", 1)[-1],
                raw_content=head,
            ),
            str(row["form"]),
            str(row["target_role"]),
            head,
        )
        if screen.screen_result != "form_match":
            direct_screen_recovery = True
            screen_context = {
                "screen_kind": _resolution_screen_kind(screen),
                "screen_result": screen.screen_result,
                "observed_body_type": screen.observed_body_type,
            }
    lazy = sgml_recovery or direct_screen_recovery
    if not lazy:
        return acquire_direct_target(
            state,
            number=number,
            requested_url=requested_url,
            response=response,
            started=started,
            finished=finished,
            source_path=source_path,
            run_root=run_root,
        )
    return acquire_lazy_target(
        row,
        state,
        run_id=run_id,
        run_root=run_root,
        staging_root=staging_root,
        response=response,
        number=number,
        requested_url=requested_url,
        started=started,
        finished=finished,
        source_path=source_path,
        fallback_selected_path=fallback_selected_path,
        fallback_selected_filename=fallback_selected_filename,
        retain_evidence=retain_evidence,
        screen_context=screen_context,
        accession=accession,
        policy=policy,
        transport=transport,
        clock=clock,
    )


__all__ = ["acquire_target"]
