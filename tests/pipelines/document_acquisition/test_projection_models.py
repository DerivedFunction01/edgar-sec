import sqlite3
import tempfile
from pathlib import Path

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.pipelines.document_acquisition.projection_models import (
    ProcessingResultProjection,
    ProjectedTarget,
    fingerprint_targets,
    projected_target_record,
)


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
