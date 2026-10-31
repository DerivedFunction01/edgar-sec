import sqlite3
import tempfile
from dataclasses import replace
from pathlib import Path

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.forms.common.exhibits import (
    DocumentRoleAssessment,
    EvidenceSpan,
    ExhibitIdentity,
)
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.pipelines.document_acquisition.project.models import (
    ProcessingResultProjection,
    ProjectedTarget,
    _projected_target_from_record,
    fingerprint_targets,
    projected_target_record,
    result_from_record,
    result_record,
)
from edgar_sec.pipelines.document_acquisition.processing.models import ProcessingResult


def _target() -> ProjectedTarget:
    return ProjectedTarget(
        target_id="target_projection",
        accession="0000320193-25-000001",
        form="10-K",
        target_role="primary",
        target_type="primary",
        source_origin="inventory_index",
        document_path="filing.txt",
        selected_filename=None,
        source_sha256="a" * 64,
        source_response_sha256="b" * 64,
        source_size=20,
        source_asset_id="asset_projection",
        source_staged_path="staging/source.txt",
        route=DocumentRoute.TEXT,
        effective_path="filing.txt",
        processing_id="processing_projection",
        operations=(),
    )


def test_fingerprint_matches_canonical_root_for_streamed_targets():
    target = _target()

    assert fingerprint_targets("run_projection", iter((target,))) == canonical_hash(
        {"run_id": "run_projection", "targets": [projected_target_record(target)]}
    )


def test_projection_iterator_round_trips_and_close_removes_spool(tmp_path: Path):
    scratch = tempfile.TemporaryDirectory(dir=tmp_path)
    database = Path(scratch.name) / "projection.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE projected_targets (target_id TEXT PRIMARY KEY, record_json TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO projected_targets VALUES (?, ?)",
            (_target().target_id, canonical_json(projected_target_record(_target()))),
        )
        connection.commit()
    finally:
        connection.close()
    projection = ProcessingResultProjection(
        run_id="run_projection",
        fingerprint="c" * 64,
        _database_path=database,
        _temporary_directory=scratch,
    )

    assert next(projection.iter_targets()) == _target()
    projection.close()

    assert not database.parent.exists()


def test_processing_result_round_trips_versioned_exhibit_assessment():
    identity = ExhibitIdentity("reg_s_k_item_601", "3.1")
    assessment = DocumentRoleAssessment(
        expected_role="exhibit",
        expected_type="EX-3.1",
        filing_form="10-K",
        expected_identity=identity,
        observed_kind="exhibit",
        observed_identity=identity,
        disposition="consistent",
        evaluator_quality="source_supported",
        profile_id="reg_s_k_item_601",
        profile_version="v1",
        diagnostic_code=None,
        diagnostic_detail=None,
        supporting_evidence=(EvidenceSpan("ex3_1_title", 12, 40),),
        contradicting_evidence=(),
        matched_evidence_tier="direct_designator",
        confidence_band="high",
        pack_id="ex3_1",
        pack_version="v1",
    )
    result = ProcessingResult(
        processing_id="processing_assessment",
        target_id="target_assessment",
        source_sha256="a" * 64,
        source_asset_id="asset_assessment",
        route=DocumentRoute.TEXT,
        effective_path="filing.txt",
        operation_results=(),
        exhibit_assessment=assessment,
        exhibit_assessment_fingerprint="b" * 64,
    )

    assert result_from_record(result_record(result)) == result


def test_projected_target_fingerprint_pins_exhibit_assessment():
    identity = ExhibitIdentity("reg_s_k_item_601", "3.1")
    assessment = DocumentRoleAssessment(
        expected_role="exhibit",
        expected_type="EX-3.1",
        filing_form="10-K",
        expected_identity=identity,
        observed_kind="exhibit",
        observed_identity=identity,
        disposition="consistent",
        evaluator_quality="source_supported",
        profile_id="reg_s_k_item_601",
        profile_version="v1",
        diagnostic_code=None,
        diagnostic_detail=None,
        supporting_evidence=(EvidenceSpan("ex3_1_title", 12, 40),),
        contradicting_evidence=(),
        matched_evidence_tier="direct_designator",
        confidence_band="high",
        pack_id="ex3_1",
        pack_version="v1",
    )
    target = replace(
        _target(),
        exhibit_assessment=assessment,
        exhibit_assessment_fingerprint="d" * 64,
    )
    record = projected_target_record(target)

    assert _projected_target_from_record(record) == target
    assert fingerprint_targets("run_projection", (target,)) != fingerprint_targets(
        "run_projection", (_target(),)
    )
