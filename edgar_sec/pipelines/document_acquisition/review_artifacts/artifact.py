from __future__ import annotations

from pathlib import Path

from edgar_sec.domain.identity import Cik
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    FixtureCaseMetadata,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.errors import (
    ProcessingReviewError,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.models import (
    ProcessingReviewArtifact,
)


OBSERVATIONS_FILE = "processing-review.json"


_ARTIFACT_VERSION = 5


def _issuer_cik(case: FixtureCaseMetadata) -> str | None:
    if case.target_url is None:
        return None
    try:
        parts = validate_archive_url(case.target_url, case.accession)
    except ValueError as error:
        raise ProcessingReviewError(
            "review artifact target URL is not an archive URL for its accession"
        ) from error
    return str(Cik.from_raw(parts.archive_cik))


def _review_payload(
    case: FixtureCaseMetadata, processing: dict[str, object]
) -> dict[str, object]:
    return {
        "artifact_type": "document_acquisition.processing_review",
        "artifact_version": _ARTIFACT_VERSION,
        "fixture": {
            "fixture_id": case.fixture_id,
            "capture_id": case.capture_id,
            "selection_source": case.selection_source,
            "inventory_entry_id": case.inventory_entry_id,
            "index_sha256": case.index_sha256,
            "target_plan_id": case.target_plan_id,
            "target_plan_digest": case.target_plan_digest,
            "target_plan_schema_version": int(case.target_plan_schema_version),
            "target_id": case.target_id,
            "source_origin": case.source_origin,
            "target_url": case.target_url,
            "retrieval_mode": case.retrieval_mode,
            "body_sha256": case.body_sha256,
            "byte_size": case.byte_size,
        },
        "capture_id": case.capture_id,
        "target_id": case.target_id,
        "accession": case.accession,
        "issuer_cik": _issuer_cik(case),
        "form": case.form,
        "target_role": case.target_role,
        "target_type": case.target_type,
        "processing": processing,
    }


def build_processing_review_artifact(
    case: FixtureCaseMetadata,
    processing: dict[str, object],
    output_path: Path,
) -> ProcessingReviewArtifact:
    payload = _review_payload(case, processing)
    artifact_sha256 = canonical_hash(payload)
    artifact = {**payload, "artifact_sha256": artifact_sha256}
    output_path = Path(output_path)
    if output_path.parent.is_symlink() or output_path.is_symlink():
        raise ProcessingReviewError("review artifact path must not be a symlink")
    encoded = canonical_json(artifact)
    if output_path.exists():
        if (
            not output_path.is_file()
            or output_path.read_text(encoding="utf-8") != encoded
        ):
            raise ProcessingReviewError(
                "review artifact conflicts with existing output"
            )
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(output_path, artifact)
    return ProcessingReviewArtifact(artifact_sha256, output_path)
