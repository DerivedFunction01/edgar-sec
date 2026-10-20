from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.engine.document.screening import (
    CandidateScreen,
    screen_specialized_xml_source,
)
from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE
from edgar_sec.infra.sec_http.streaming import (
    StreamFailure,
    StreamResult,
    StreamedResponse,
)
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
    build_resolution as _resolution,
)
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


def validate_redirect(
    url: str,
    accession: AccessionNumber,
    expected_archive_cik: str | int | None = None,
) -> None:
    try:
        validate_archive_url(url, accession, expected_archive_cik=expected_archive_cik)
    except ValueError as error:
        raise ValueError("redirect URL is malformed") from error


def stream(
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
        validate_redirect=lambda redirect: validate_redirect(
            redirect, accession, expected_archive_cik
        ),
    )
    if isinstance(result, StreamedResponse):
        try:
            validate_redirect(result.final_url, accession, expected_archive_cik)
        except ValueError:
            result.path.unlink(missing_ok=True)
            return StreamFailure(
                "unsafe_redirect",
                False,
                result.status_code,
                "response final URL is outside the requested accession",
            )
    return result


def has_lazy_index_trigger(row: dict[str, object]) -> bool:
    trigger_id, trigger_version = (
        row["lazy_index_trigger_id"],
        row["lazy_index_trigger_version"],
    )
    if (trigger_id is None) != (trigger_version is None):
        raise ValueError("lazy-index trigger ID and version must be pinned together")
    if trigger_id is None:
        return False
    if not (
        isinstance(trigger_id, str)
        and trigger_id
        and isinstance(trigger_version, str)
        and trigger_version
    ):
        raise ValueError("lazy-index trigger pin is invalid")
    return True


def apply_structure_screen(
    screen: CandidateScreen,
    form: str,
    role: str,
    content: bytes,
) -> CandidateScreen:
    if screen.is_inversion or role != "primary":
        return screen
    structure = screen_specialized_xml_source(form, content)
    if structure.is_inversion:
        return structure
    if (
        structure.screen_result == "form_match"
        and screen.screen_result == "unverifiable"
    ):
        return structure
    return screen


def read_screen_head(path: Path) -> bytes:
    try:
        with path.open("rb") as source:
            return source.read(DEFAULT_IO_CHUNK_SIZE)
    except OSError:
        return b""


def resolution_screen_kind(screen: CandidateScreen) -> str:
    return "sgml_type" if screen.screen_kind == "sgml_type" else "html_cover"


def unresolved_source_outcome(
    *,
    row: dict[str, object],
    state: TargetState,
    run_id: str,
    run_root: Path,
    response: StreamedResponse,
    first_attempt: AcquisitionAttempt,
    index_attempt: AcquisitionAttempt,
    index_response: StreamedResponse | None,
    index_result: str,
    number: int,
    started: str,
    finished: str,
    source_path: Path,
    selected_path: Path,
    selected_filename: str | None,
    retain_evidence: bool,
    screen_context: dict[str, str | None],
    clock: Callable[[], datetime],
    extra_attempts: tuple[AcquisitionAttempt, ...] = (),
    fallback_number: int | None = None,
) -> tuple[
    tuple[AcquisitionAttempt, ...],
    AcquisitionOutcome,
    TargetSlotResolution,
    str,
]:
    fallback_attempt = _attempt(
        target_id=state.target_id,
        number=fallback_number or number + 2,
        kind="document_body",
        requested_url=str(row["target_url"]),
        result=response,
        started_at_utc=started,
        finished_at_utc=finished,
        source_path=source_path if retain_evidence else None,
        selected_path=selected_path,
        run_root=run_root,
        selected_filename=selected_filename,
    )
    attempts = (first_attempt, index_attempt, *extra_attempts, fallback_attempt)
    resolution = _resolution(
        row | {"run_id": run_id},
        response,
        index_attempt,
        index_response,
        None,
        index_result,
        **screen_context,
    )
    fallback_outcome = outcome(
        state.target_id,
        attempts,
        "acquired",
        source_sha256=response.sha256,
        source_byte_size=response.byte_size,
        selected_sha256=fallback_attempt.selected_sha256,
        selected_byte_size=fallback_attempt.selected_byte_size,
        selected_path=_relative(run_root, selected_path),
    )
    return attempts, fallback_outcome, resolution, _utc(clock)


def outcome(
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


def _utc(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("acquisition clock must return timezone-aware datetimes")
    return value.astimezone(UTC).isoformat(timespec="seconds")
