from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.review.paths import ReviewPaths
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    FixtureCaseMetadata,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.review_artifacts.artifact import (
    OBSERVATIONS_FILE,
    build_processing_review_artifact,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.case_processing import (
    _case_id,
    _process_fixture_body,
    _validated_fixture_body,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.models import (
    ProcessingReviewArtifact,
)


def _manifest_record(
    case: FixtureCaseMetadata,
    review_id: str,
    paths: ReviewPaths,
    *,
    status: str,
    output: ProcessingReviewArtifact | None,
    error: str | None = None,
) -> dict[str, object]:
    outputs = {}
    if output is not None:
        relative = output.path.relative_to(paths.root)
        outputs[OBSERVATIONS_FILE] = {
            "path": str(relative),
            "sha256": file_sha256(output.path),
        }
    return {
        "review_id": review_id,
        "fixture_id": case.fixture_id,
        "capture_id": case.capture_id,
        "target_id": case.target_id,
        "accession": case.accession,
        "target_plan_id": case.target_plan_id,
        "target_plan_digest": case.target_plan_digest,
        "target_plan_schema_version": int(case.target_plan_schema_version),
        "body_sha256": case.body_sha256,
        "status": status,
        "outputs": outputs,
        "error": None if error is None else error[:2000],
    }


def _process_review_case_worker(
    case: FixtureCaseMetadata,
    paths: AcquisitionPaths,
    case_root: Path,
    staging_root: Path,
    review_paths: ReviewPaths,
) -> tuple[str, ProcessingReviewArtifact | None, str | None]:
    status = "execution_error"
    artifact = None
    error = None
    raw_bytes = b""
    info_path = staging_root / ".case_info.json"
    atomic_write_json(
        info_path,
        {
            "accession": case.accession,
            "case_id": _case_id(case),
            "fixture_id": case.fixture_id,
            "form": case.form,
            "target_id": case.target_id,
            "selected_filename": case.selected_filename,
        },
    )
    with tempfile.TemporaryDirectory(prefix="fixture-body-") as temporary:
        body_path = Path(temporary) / "selected-body.bin"
        try:
            raw_bytes = _validated_fixture_body(case, paths, body_path)
        except Exception as exception:
            status = "fixture_verification_failure"
            error = str(exception) or type(exception).__name__
        else:
            try:
                processing = _process_fixture_body(
                    case, body_path, raw_bytes, staging_root
                )
                artifact = build_processing_review_artifact(
                    case, processing, staging_root / OBSERVATIONS_FILE
                )
                case_root.parent.mkdir(parents=True, exist_ok=True)
                info_path.unlink(missing_ok=True)
                os.replace(staging_root, case_root)
                artifact = ProcessingReviewArtifact(
                    artifact.artifact_sha256, case_root / OBSERVATIONS_FILE
                )
                status = "complete"
            except Exception as exception:
                error = str(exception) or type(exception).__name__
    if status != "complete":
        shutil.rmtree(staging_root, ignore_errors=True)
    del raw_bytes
    return status, artifact, error
