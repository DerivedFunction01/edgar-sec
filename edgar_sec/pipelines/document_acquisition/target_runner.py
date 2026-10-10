"""Acquire one validated S9 target with bounded response staging."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from shutil import copyfile
from typing import Protocol

from edgar_sec.domain.document_inventory.models import IndexPageInput
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import full_submission_url_for, validate_archive_url
from edgar_sec.engine.document.unpacking.streaming import (
    BundleExtraction,
    extract_bundle_sequence,
)
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.infra.sec_http.streaming import (
    StreamFailure,
    StreamResult,
    StreamedResponse,
)
from edgar_sec.pipelines.document_acquisition.index_selection import (
    IndexSelection,
    select_index_entry,
)
from edgar_sec.pipelines.document_acquisition.attempts import (
    build_attempt as _attempt,
    relative_path as _relative,
)
from edgar_sec.pipelines.document_acquisition.resolution import (
    build_resolution as _resolution,
    screen_sgml_type as _screen_sgml_type,
)
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    AcquisitionPolicy,
    AcquisitionStatus,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.run_state.models import TargetState


class AcquisitionTransport(Protocol):
    def stream_to_file(
        self,
        url: str,
        destination: str | Path,
        *,
        max_response_bytes: int,
        validate_redirect: Callable[[str], None],
    ) -> StreamResult: ...


def _utc(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("acquisition clock must return timezone-aware datetimes")
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _new_path(staging_root: Path, prefix: str) -> Path:
    return staging_root / f"{prefix}-{uuid.uuid4().hex}.bin"


def _validate_redirect(
    url: str,
    accession: AccessionNumber,
    expected_archive_cik: str | int | None = None,
) -> None:
    try:
        validate_archive_url(url, accession, expected_archive_cik=expected_archive_cik)
    except ValueError as error:
        raise ValueError("redirect URL is malformed") from error


def _stream(
    transport: AcquisitionTransport,
    url: str,
    destination: Path,
    accession: AccessionNumber,
    policy: AcquisitionPolicy,
) -> StreamResult:
    try:
        archive = validate_archive_url(url, accession)
    except ValueError as error:
        raise ValueError("redirect URL is malformed") from error
    expected_archive_cik = archive.archive_cik
    result = transport.stream_to_file(
        url,
        destination,
        max_response_bytes=policy.max_response_bytes,
        validate_redirect=lambda redirect: _validate_redirect(
            redirect, accession, expected_archive_cik
        ),
    )
    if isinstance(result, StreamedResponse):
        try:
            _validate_redirect(result.final_url, accession, expected_archive_cik)
        except ValueError:
            result.path.unlink(missing_ok=True)
            return StreamFailure(
                "unsafe_redirect",
                False,
                result.status_code,
                "response final URL is outside the requested accession",
            )
    return result


def _outcome(
    target_id: str,
    attempts: tuple[AcquisitionAttempt, ...],
    status: AcquisitionStatus,
    *,
    error_code: str | None = None,
    source_sha256: str | None = None,
    source_byte_size: int | None = None,
    source_path: Path | None = None,
    selected_sha256: str | None = None,
    selected_byte_size: int | None = None,
    selected_path: Path | None = None,
) -> AcquisitionOutcome:
    last = attempts[-1]
    return AcquisitionOutcome(
        target_id=target_id,
        source=last.source,
        status=status,
        attempt_count=last.attempt_number,
        last_attempt_id=last.attempt_id,
        error_code=error_code,
        retryable=last.retryable if status == "failed" else False,
        source_sha256=source_sha256,
        source_byte_size=source_byte_size,
        source_body_relative_path=source_path,
        selected_sha256=selected_sha256,
        selected_byte_size=selected_byte_size,
        body_lifecycle="staged" if status == "acquired" else None,
        selected_body_relative_path=selected_path,
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
    retain_evidence = (
        policy.retain_response_evidence
        and row["target_role"] == "primary"
        and (
            row["retrieval_mode"] == "bundle_sequence"
            or (
                row["source_origin"] == "catalog_direct"
                and row["catalog_direct_selection"] == "exact_form_with_lazy_index"
            )
        )
    )
    source_path = _new_path(staging_root, "response")
    selected_path: Path | None = None
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
    screen_context: dict[str, str | None] = {
        "screen_kind": "html_cover",
        "screen_result": "unverifiable",
        "observed_body_type": None,
    }
    if row["retrieval_mode"] == "bundle_sequence":
        sequence = row["sequence"]
        selected_path = _new_path(staging_root, "selected")
        extracted = extract_bundle_sequence(
            response.path,
            sequence,
            selected_path,
            expected_source_sha256=response.sha256,
        )
        if isinstance(extracted, BundleExtraction):
            should_screen_sgml = (
                row["source_origin"] == "catalog_direct"
                and row["target_role"] == "primary"
                and row["catalog_direct_selection"] == "exact_form_with_lazy_index"
            )
            screen_result = (
                _screen_sgml_type(extracted.selected.document_type, str(row["form"]))
                if should_screen_sgml
                else "form_match"
            )
            if screen_result != "form_match":
                sgml_recovery = True
                screen_context = {
                    "screen_kind": "sgml_type",
                    "screen_result": screen_result,
                    "observed_body_type": extracted.selected.document_type,
                }
                selected_path.unlink(missing_ok=True)
            else:
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
                return (attempt,), outcome, None, None
        else:
            if not retain_evidence:
                response.path.unlink(missing_ok=True)
            selected_path.unlink(missing_ok=True)
            status: AcquisitionStatus = (
                "not_filed"
                if extracted.code == "sequence_not_found"
                else "ambiguous"
                if extracted.code == "duplicate_sequence"
                else "failed"
            )
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
            return (
                (attempt,),
                _outcome(
                    state.target_id,
                    (attempt,),
                    status,
                    error_code=extracted.code if status == "failed" else None,
                ),
                None,
                None,
            )

    lazy = sgml_recovery or (
        row["source_origin"] == "catalog_direct"
        and row["target_role"] == "primary"
        and row["catalog_direct_selection"] == "exact_form_with_lazy_index"
        and row["sequence"] == 1
    )
    if not lazy:
        selected_path = source_path
        attempt = _attempt(
            target_id=state.target_id,
            number=number,
            kind="document_body",
            requested_url=requested_url,
            result=response,
            started_at_utc=started,
            finished_at_utc=finished,
            source_path=source_path,
            selected_path=selected_path,
            run_root=run_root,
        )
        outcome = _outcome(
            state.target_id,
            (attempt,),
            "acquired",
            source_sha256=response.sha256,
            source_byte_size=response.byte_size,
            source_path=_relative(run_root, source_path),
            selected_sha256=response.sha256,
            selected_byte_size=response.byte_size,
            selected_path=_relative(run_root, source_path),
        )
        if (
            attempt.selected_sha256 != response.sha256
            or attempt.selected_byte_size != response.byte_size
        ):
            source_path.unlink(missing_ok=True)
            failed_attempt = _attempt(
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
                outcome="failed",
                error_code="source_mismatch",
            )
            return (
                (failed_attempt,),
                _outcome(
                    state.target_id,
                    (failed_attempt,),
                    "failed",
                    error_code="source_mismatch",
                ),
                None,
                None,
            )
        return (attempt,), outcome, None, None

    first_attempt = _attempt(
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
    )
    if not retain_evidence:
        source_path.unlink(missing_ok=True)
    archive_cik = validate_archive_url(requested_url, accession).archive_cik
    index_url = full_submission_url_for(archive_cik, str(accession))
    index_url = index_url.removesuffix(".txt") + "-index.html"
    index_path = _new_path(staging_root, "index")
    index_started = _utc(clock)
    index_result = _stream(transport, index_url, index_path, accession, policy)
    index_finished = _utc(clock)
    if isinstance(index_result, StreamFailure):
        index_attempt = _attempt(
            target_id=state.target_id,
            number=number + 1,
            kind="lazy_index",
            requested_url=index_url,
            result=index_result,
            started_at_utc=index_started,
            finished_at_utc=index_finished,
            source_path=None,
            selected_path=None,
            run_root=run_root,
        )
        resolution = _resolution(
            row | {"run_id": run_id},
            response,
            index_attempt,
            None,
            None,
            "failed",
            **screen_context,
        )
        attempts = (first_attempt, index_attempt)
        return (
            attempts,
            _outcome(
                state.target_id,
                attempts,
                "failed",
                error_code=index_result.code,
                source_sha256=response.sha256,
                source_byte_size=response.byte_size,
            ),
            resolution,
            _utc(clock),
        )

    index_bytes = index_result.path.read_bytes()
    parsed = parse_html_index(
        IndexPageInput(accession, index_result.final_url, index_bytes)
    )
    selection = select_index_entry(
        parsed,
        accession=accession,
        expected_form=str(row["form"]),
        optional=bool(row["optional"]),
    )
    if parsed.page_sha256 != index_result.sha256:
        selection = IndexSelection("failed", (), None, "index_response_mismatch")
    index_attempt = _attempt(
        target_id=state.target_id,
        number=number + 1,
        kind="lazy_index",
        requested_url=index_url,
        result=index_result,
        started_at_utc=index_started,
        finished_at_utc=index_finished,
        source_path=index_result.path if retain_evidence else None,
        selected_path=None,
        run_root=run_root,
    )
    if not retain_evidence:
        index_result.path.unlink(missing_ok=True)
    attempts = (first_attempt, index_attempt)
    if selection.result != "selected":
        status = selection.result
        resolution = _resolution(
            row | {"run_id": run_id},
            response,
            index_attempt,
            index_result,
            selection,
            "not_filed" if status == "not_filed" else status,
            **screen_context,
        )
        return (
            attempts,
            _outcome(
                state.target_id,
                attempts,
                status,
                error_code=selection.error_code,
                source_sha256=response.sha256,
                source_byte_size=response.byte_size,
            ),
            resolution,
            _utc(clock),
        )

    entry = selection.entry
    if entry is None or selection.selected_url is None:
        raise ValueError("selected index entry is not addressable")
    body_source_path = _new_path(staging_root, "body-source")
    body_started = _utc(clock)
    body_result = _stream(
        transport, selection.selected_url, body_source_path, accession, policy
    )
    body_finished = _utc(clock)
    if isinstance(body_result, StreamFailure):
        body_attempt = _attempt(
            target_id=state.target_id,
            number=number + 2,
            kind="document_body",
            requested_url=selection.selected_url,
            result=body_result,
            started_at_utc=body_started,
            finished_at_utc=body_finished,
            source_path=None,
            selected_path=None,
            run_root=run_root,
        )
        attempts = (*attempts, body_attempt)
        resolution = _resolution(
            row | {"run_id": run_id},
            response,
            index_attempt,
            index_result,
            selection,
            "failed",
            **screen_context,
        )
        return (
            attempts,
            _outcome(
                state.target_id,
                attempts,
                "failed",
                error_code=body_result.code,
                source_sha256=response.sha256,
                source_byte_size=response.byte_size,
            ),
            resolution,
            _utc(clock),
        )
    if selection.retrieval_mode == "bundle_sequence":
        if entry.sequence is None:
            raise ValueError("selected bundle entry has no sequence")
        selected_path = _new_path(staging_root, "selected")
        extracted = extract_bundle_sequence(
            body_result.path,
            entry.sequence,
            selected_path,
            expected_source_sha256=body_result.sha256,
        )
        if not retain_evidence:
            body_result.path.unlink(missing_ok=True)
        if not isinstance(extracted, BundleExtraction):
            selected_path.unlink(missing_ok=True)
            status: AcquisitionStatus = (
                "ambiguous" if extracted.code == "duplicate_sequence" else "failed"
            )
            body_attempt = _attempt(
                target_id=state.target_id,
                number=number + 2,
                kind="document_body",
                requested_url=selection.selected_url,
                result=body_result,
                started_at_utc=body_started,
                finished_at_utc=body_finished,
                source_path=body_result.path if retain_evidence else None,
                selected_path=None,
                run_root=run_root,
                outcome=status,
                error_code=extracted.code if status == "failed" else None,
            )
            attempts = (*attempts, body_attempt)
            resolution = _resolution(
                row | {"run_id": run_id},
                response,
                index_attempt,
                index_result,
                selection,
                "failed",
                **screen_context,
            )
            return (
                attempts,
                _outcome(
                    state.target_id,
                    attempts,
                    status,
                    error_code=extracted.code if status == "failed" else None,
                ),
                resolution,
                _utc(clock),
            )
        if row["catalog_direct_selection"] == "exact_form_with_lazy_index":
            screen_result = _screen_sgml_type(
                extracted.selected.document_type, str(row["form"])
            )
            if screen_result != "form_match":
                selected_path.unlink(missing_ok=True)
                body_attempt = _attempt(
                    target_id=state.target_id,
                    number=number + 2,
                    kind="document_body",
                    requested_url=selection.selected_url,
                    result=body_result,
                    started_at_utc=body_started,
                    finished_at_utc=body_finished,
                    source_path=body_result.path if retain_evidence else None,
                    selected_path=None,
                    run_root=run_root,
                    outcome="failed",
                    error_code=(
                        "document_type_mismatch"
                        if screen_result == "type_mismatch"
                        else "document_type_unverifiable"
                    ),
                )
                attempts = (*attempts, body_attempt)
                resolution = _resolution(
                    row | {"run_id": run_id},
                    response,
                    index_attempt,
                    index_result,
                    selection,
                    "failed",
                    **screen_context,
                )
                return (
                    attempts,
                    _outcome(
                        state.target_id,
                        attempts,
                        "failed",
                        error_code=body_attempt.error_code,
                    ),
                    resolution,
                    _utc(clock),
                )
        body_attempt = _attempt(
            target_id=state.target_id,
            number=number + 2,
            kind="document_body",
            requested_url=selection.selected_url,
            result=body_result,
            started_at_utc=body_started,
            finished_at_utc=body_finished,
            source_path=body_result.path if retain_evidence else None,
            selected_path=selected_path,
            run_root=run_root,
        )
        if (
            body_attempt.selected_sha256 != extracted.body_sha256
            or body_attempt.selected_byte_size != extracted.body_size
        ):
            selected_path.unlink(missing_ok=True)
            body_attempt = _attempt(
                target_id=state.target_id,
                number=number + 2,
                kind="document_body",
                requested_url=selection.selected_url,
                result=body_result,
                started_at_utc=body_started,
                finished_at_utc=body_finished,
                source_path=body_result.path if retain_evidence else None,
                selected_path=None,
                run_root=run_root,
                outcome="failed",
                error_code="source_mismatch",
            )
            attempts = (*attempts, body_attempt)
            resolution = _resolution(
                row | {"run_id": run_id},
                response,
                index_attempt,
                index_result,
                selection,
                "failed",
                **screen_context,
            )
            return (
                attempts,
                _outcome(
                    state.target_id,
                    attempts,
                    "failed",
                    error_code="source_mismatch",
                ),
                resolution,
                _utc(clock),
            )
        attempts = (*attempts, body_attempt)
        resolution = _resolution(
            row | {"run_id": run_id},
            response,
            index_attempt,
            index_result,
            selection,
            "recovered",
            **screen_context,
        )
        return (
            attempts,
            _outcome(
                state.target_id,
                attempts,
                "acquired",
                source_sha256=body_result.sha256,
                source_byte_size=body_result.byte_size,
                selected_sha256=extracted.body_sha256,
                selected_byte_size=extracted.body_size,
                selected_path=_relative(run_root, selected_path),
            ),
            resolution,
            _utc(clock),
        )
    if retain_evidence:
        selected_path = _new_path(staging_root, "selected")
        copyfile(body_result.path, selected_path)
    else:
        selected_path = body_result.path
    body_attempt = _attempt(
        target_id=state.target_id,
        number=number + 2,
        kind="document_body",
        requested_url=selection.selected_url,
        result=body_result,
        started_at_utc=body_started,
        finished_at_utc=body_finished,
        source_path=body_result.path if retain_evidence else None,
        selected_path=selected_path,
        run_root=run_root,
    )
    attempts = (*attempts, body_attempt)
    if (
        body_attempt.selected_sha256 != body_result.sha256
        or body_attempt.selected_byte_size != body_result.byte_size
    ):
        selected_path.unlink(missing_ok=True)
        body_attempt = _attempt(
            target_id=state.target_id,
            number=number + 2,
            kind="document_body",
            requested_url=selection.selected_url,
            result=body_result,
            started_at_utc=body_started,
            finished_at_utc=body_finished,
            source_path=body_result.path if retain_evidence else None,
            selected_path=None,
            run_root=run_root,
            outcome="failed",
            error_code="source_mismatch",
        )
        attempts = (*attempts[:-1], body_attempt)
        resolution = _resolution(
            row | {"run_id": run_id},
            response,
            index_attempt,
            index_result,
            selection,
            "failed",
            **screen_context,
        )
        return (
            attempts,
            _outcome(
                state.target_id,
                attempts,
                "failed",
                error_code="source_mismatch",
            ),
            resolution,
            _utc(clock),
        )
    resolution = _resolution(
        row | {"run_id": run_id},
        response,
        index_attempt,
        index_result,
        selection,
        "recovered",
        **screen_context,
    )
    outcome = _outcome(
        state.target_id,
        attempts,
        "acquired",
        source_sha256=body_result.sha256,
        source_byte_size=body_result.byte_size,
        source_path=None,
        selected_sha256=body_result.sha256,
        selected_byte_size=body_result.byte_size,
        selected_path=_relative(run_root, selected_path),
    )
    return attempts, outcome, resolution, _utc(clock)


__all__ = ["AcquisitionTransport", "acquire_target"]
