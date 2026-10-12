from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from edgar_sec.engine.document.unpacking.streaming import (
    BundleExtraction,
    extract_bundle_sequence,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    FixtureCaseMetadata,
    get_fixture_case,
    iter_fixture_cases,
    iter_fixture_ids,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureOperationError,
    ResponseBodyRef,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.replay import (
    replay_fixture_response,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths


@dataclass(frozen=True, slots=True)
class FixtureReplayResult:
    fixture_id: str
    capture_id: str
    target_id: str
    attempt_id: str
    acquisition_status: str
    response_sha256: str | None
    selected_sha256: str | None
    selected_byte_size: int | None
    output_path: Path | None


def list_fixtures(paths: AcquisitionPaths) -> Iterator[str]:
    return iter_fixture_ids(paths)


def list_fixture_cases(
    paths: AcquisitionPaths,
    *,
    fixture_id: str | None = None,
    capture_id: str | None = None,
    target_id: str | None = None,
) -> Iterator[FixtureCaseMetadata]:
    return iter_fixture_cases(
        paths,
        fixture_id=fixture_id,
        capture_id=capture_id,
        target_id=target_id,
    )


def _publish_new_file(staged_path: Path, output_path: Path) -> Path:
    output = Path(output_path).expanduser()
    parent = output.parent.resolve(strict=True)
    if not parent.is_dir():
        raise FixtureOperationError("replay output parent is not a directory")
    destination = parent / output.name
    if destination.exists() or destination.is_symlink():
        raise FixtureOperationError("replay output already exists")
    try:
        os.link(staged_path, destination)
    except FileExistsError as error:
        raise FixtureOperationError("replay output already exists") from error
    return destination


def _replay_destination(paths: AcquisitionPaths, output_path: Path) -> Path:
    output = Path(output_path).expanduser()
    parent = output.parent.resolve(strict=True)
    if not parent.is_dir():
        raise FixtureOperationError("replay output parent is not a directory")
    destination = parent / output.name
    if destination.exists() or destination.is_symlink():
        raise FixtureOperationError("replay output already exists")
    for root in (
        paths.fixtures_root,
        paths.runs_root,
        paths.snapshots_root,
        paths.review_runs_root,
    ):
        if destination.is_relative_to(root.resolve()):
            raise FixtureOperationError(
                "replay output cannot be inside managed artifacts"
            )
    return destination


def _replay_response(
    paths: AcquisitionPaths,
    fixture_id: str,
    case: FixtureCaseMetadata,
    staged_path: Path,
) -> ResponseBodyRef:
    if case.response_sha256 is None:
        raise FixtureOperationError("acquired fixture case has no response body")
    with staged_path.open("xb") as destination:
        return replay_fixture_response(
            paths, fixture_id, case.response_sha256, destination
        )


class _DiscardResponse:
    def write(self, chunk: bytes) -> int:
        return len(chunk)


def _verify_related_response(
    paths: AcquisitionPaths, fixture_id: str, digest: str | None
) -> None:
    if digest is not None:
        replay_fixture_response(paths, fixture_id, digest, _DiscardResponse())


def _replay_selected_body(
    paths: AcquisitionPaths,
    fixture_id: str,
    case: FixtureCaseMetadata,
    temporary_root: Path,
) -> tuple[Path, ResponseBodyRef]:
    source_path = temporary_root / "source-response.bin"
    response_ref = _replay_response(paths, fixture_id, case, source_path)
    selected_path = temporary_root / "selected-body.bin"
    if case.resolution_schema_version is None:
        _verify_related_response(paths, fixture_id, case.index_response_sha256)
        _verify_related_response(paths, fixture_id, case.selected_response_sha256)
    if case.resolution_schema_version is not None:
        _verify_related_response(paths, fixture_id, case.index_response_sha256)
        if case.selected_response_sha256 is None:
            raise FixtureOperationError("resolution case has no selected response body")
        with selected_path.open("xb") as selected_file:
            selected_ref = replay_fixture_response(
                paths,
                fixture_id,
                case.selected_response_sha256,
                selected_file,
            )
        if case.selected_retrieval_mode == "direct_url":
            if (
                selected_ref.response_sha256 != case.selected_sha256
                or selected_ref.byte_size != case.selected_byte_size
                or case.selected_url is None
                or urlsplit(case.selected_url).path.rsplit("/", 1)[-1]
                != case.selected_filename
            ):
                raise FixtureOperationError(
                    "replayed selected response differs from captured evidence"
                )
            return selected_path, response_ref
        if (
            case.selected_retrieval_mode != "bundle_sequence"
            or case.selected_sequence is None
        ):
            raise FixtureOperationError(
                "resolution has invalid selected bundle metadata"
            )
        extracted = extract_bundle_sequence(
            selected_path,
            case.selected_sequence,
            temporary_root / "selected-child.bin",
            expected_source_sha256=selected_ref.response_sha256,
        )
        if not isinstance(extracted, BundleExtraction):
            raise FixtureOperationError(
                f"selected bundle replay failed: {extracted.code}"
            )
        if (
            extracted.body_sha256 != case.selected_sha256
            or extracted.body_size != case.selected_byte_size
            or extracted.selected.filename
            != (case.selected_filename or f"sequence-{case.selected_sequence}")
        ):
            raise FixtureOperationError(
                "replayed selected bundle body differs from captured evidence"
            )
        return temporary_root / "selected-child.bin", response_ref
    if case.retrieval_mode == "direct_url":
        if (
            case.selected_sha256 != response_ref.response_sha256
            or case.selected_byte_size != response_ref.byte_size
        ):
            raise FixtureOperationError(
                "direct replay response differs from selected body"
            )
        return source_path, response_ref
    if case.sequence is None or case.selected_sha256 is None:
        raise FixtureOperationError("bundle fixture case has incomplete selection data")
    extraction = extract_bundle_sequence(
        source_path,
        case.sequence,
        selected_path,
        expected_source_sha256=response_ref.response_sha256,
    )
    if not isinstance(extraction, BundleExtraction):
        raise FixtureOperationError(
            f"bundle fixture extraction failed: {extraction.code}"
        )
    if (
        extraction.body_sha256 != case.selected_sha256
        or extraction.body_size != case.selected_byte_size
        or extraction.selected.filename
        != (case.selected_filename or f"sequence-{case.sequence}")
    ):
        raise FixtureOperationError(
            "replayed bundle body differs from captured evidence"
        )
    return selected_path, response_ref


def replay_fixture_case(
    fixture_id: str,
    capture_id: str,
    target_id: str,
    output_path: Path,
    *,
    paths: AcquisitionPaths,
) -> FixtureReplayResult:
    case = get_fixture_case(paths, fixture_id, capture_id, target_id)
    if case.acquisition_status != "acquired":
        _verify_related_response(paths, fixture_id, case.response_sha256)
        _verify_related_response(paths, fixture_id, case.index_response_sha256)
        _verify_related_response(paths, fixture_id, case.selected_response_sha256)
        return FixtureReplayResult(
            fixture_id,
            capture_id,
            target_id,
            case.attempt_id,
            case.acquisition_status,
            case.response_sha256,
            None,
            None,
            None,
        )
    if case.selected_sha256 is None or case.selected_byte_size is None:
        raise FixtureOperationError(
            "acquired fixture case has no selected-body identity"
        )
    destination = _replay_destination(paths, output_path)
    parent = destination.parent
    with tempfile.TemporaryDirectory(prefix="acq-replay-", dir=parent) as temporary:
        selected_path, response_ref = _replay_selected_body(
            paths, fixture_id, case, Path(temporary)
        )
        output_path = _publish_new_file(selected_path, destination)
    return FixtureReplayResult(
        fixture_id,
        capture_id,
        target_id,
        case.attempt_id,
        "acquired",
        response_ref.response_sha256,
        case.selected_sha256,
        case.selected_byte_size,
        output_path,
    )
