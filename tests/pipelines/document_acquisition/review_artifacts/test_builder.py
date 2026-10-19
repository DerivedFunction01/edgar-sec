from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar_sec.engine.document_processing.processor import AcquisitionProcessor
from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.review.paths import (
    PIPELINE_REVIEW_MANIFEST_FILE,
    ReviewPaths,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    _materialize_fixture_case,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    initialize_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import FixturePlanPin
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.review_artifacts import builder
from edgar_sec.pipelines.document_acquisition.review_artifacts.analyzer import (
    analyze_review_run,
)
from tests.pipelines.document_acquisition.fixture_store.fixture_helpers import (
    append_test_lazy_index,
    append_test_case,
)

_FIXTURE_ID = "fixture-form4"
_BODY = (
    b"<html><body><table><tr><td>Form 4 parser fixture</td></tr></table></body></html>"
)


def _fixture(paths, body: bytes = _BODY):
    initialize_fixture(
        paths,
        _FIXTURE_ID,
        FixturePlanPin("plan-form4", "a" * 64, 1),
    )
    index_ref = append_test_lazy_index(paths, _FIXTURE_ID, b"<html>cached index</html>")
    append_test_case(
        paths,
        _FIXTURE_ID,
        "target-form4",
        body,
        pin=FixturePlanPin("plan-form4", "a" * 64, 1),
        selection_source="fixture_lazy_index",
        index_sha256=index_ref.body_sha256,
        source_origin="catalog_direct",
    )
    return index_ref


def test_review_generator_parses_verified_form4_fixture_bytes_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    index_ref = _fixture(paths)
    calls = []
    process = AcquisitionProcessor.process
    verify_index = builder.verify_fixture_lazy_index
    index_verifications = []

    def traced_process(self, request):
        calls.append(request.inputs[0].raw_bytes)
        return process(self, request)

    def traced_index(paths, fixture_id, accession, expected_sha256):
        index_verifications.append((fixture_id, accession, expected_sha256))
        return verify_index(paths, fixture_id, accession, expected_sha256)

    monkeypatch.setattr(AcquisitionProcessor, "process", traced_process)
    monkeypatch.setattr(builder, "verify_fixture_lazy_index", traced_index)
    output = tmp_path / "review-run"

    result = builder.build_review_artifacts(
        _FIXTURE_ID, output, paths=paths, no_progress=True
    )

    assert result.summary.total == result.summary.completed == 1
    assert calls == [_BODY]
    assert len(index_verifications) == 1
    review_paths = ReviewPaths(output, PIPELINE_REVIEW_MANIFEST_FILE)
    record = json.loads(review_paths.manifest_path.read_text(encoding="utf-8"))
    artifact_path = output / record["outputs"][builder.OBSERVATIONS_FILE]["path"]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["artifact_version"] == 4
    assert artifact["fixture"]["body_sha256"] == sha256_bytes(_BODY)
    assert artifact["fixture"]["index_sha256"] == index_ref.body_sha256
    operations = {
        item["operation"]: item for item in artifact["processing"]["operations"]
    }
    assert set(operations) == {"raw", "render_to_txt", "render_to_xml"}
    assert operations["raw"]["status"] == "available"
    assert operations["raw"]["output"]["sha256"] == sha256_bytes(_BODY)
    assert operations["render_to_xml"]["status"] == "available"
    assert operations["render_to_xml"]["handler_id"] == "form4_html_to_xml"
    unparsed_path = artifact_path.parent / "operations" / "unparsed_sections.json"
    unparsed_payload = json.loads(unparsed_path.read_text(encoding="utf-8"))
    assert set(unparsed_payload) == {"unparsed_sections"}
    assert isinstance(unparsed_payload["unparsed_sections"], list)
    assert artifact["processing"]["outputs"]["operations/unparsed_sections.json"] == {
        "sha256": file_sha256(unparsed_path),
        "byte_size": unparsed_path.stat().st_size,
    }
    for relative, output_info in artifact["processing"]["outputs"].items():
        path = artifact_path.parent / relative
        assert file_sha256(path) == output_info["sha256"]
    assert artifact["artifact_sha256"] == canonical_hash(
        {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    )
    assert analyze_review_run(output)["case_status_counts"] == {"complete": 1}


def test_review_generator_records_fixture_body_verification_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    _fixture(paths)

    def corrupt(_fixture_id, _capture_id, _target_id, destination, *, paths):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"tampered")
        return SimpleNamespace(body_sha256=sha256_bytes(_BODY), byte_size=len(_BODY))

    monkeypatch.setattr(builder, "_materialize_fixture_case", corrupt)
    output = tmp_path / "review-run"

    result = builder.build_review_artifacts(
        _FIXTURE_ID, output, paths=paths, no_progress=True
    )

    assert result.summary.fixture_verification_failure == 1
    record = json.loads(
        ReviewPaths(output, PIPELINE_REVIEW_MANIFEST_FILE).manifest_path.read_text(
            encoding="utf-8"
        )
    )
    assert record["status"] == "fixture_verification_failure"
    assert record["outputs"] == {}


def test_review_generator_requires_fixture_cases(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_fixture(
        paths,
        _FIXTURE_ID,
        FixturePlanPin("plan-form4", "a" * 64, 1),
    )

    with pytest.raises(ValueError, match="no parser-body cases"):
        builder.build_review_artifacts(
            _FIXTURE_ID, tmp_path / "review-run", paths=paths, no_progress=True
        )


def test_reader_materializes_the_case_used_by_parser_review(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    _fixture(paths)
    output = tmp_path / "body.bin"
    materialized = _materialize_fixture_case(
        _FIXTURE_ID, "capture-1", "target-form4", output, paths=paths
    )

    assert materialized.body_sha256 == sha256_bytes(_BODY)
    assert materialized.byte_size == len(_BODY)
    assert output.read_bytes() == _BODY
