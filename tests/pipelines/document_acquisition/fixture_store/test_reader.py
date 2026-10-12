from __future__ import annotations

import hashlib
import io

from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    replay_fixture_case,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    append_fixture_case,
    initialize_fixture,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths


def test_replay_reextracts_and_verifies_a_bundle_case(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_fixture(paths, "fixture-bundle")
    bundle = (
        b"<DOCUMENT><SEQUENCE>2<FILENAME>report.htm<TYPE>10-K<TEXT>selected body"
        b"</TEXT></DOCUMENT>"
    )
    selected_body = b"selected body"
    source_digest = hashlib.sha256(bundle).hexdigest()
    selected_digest = hashlib.sha256(selected_body).hexdigest()
    capture = {
        "capture_id": "capture-bundle",
        "run_id": "run-bundle",
        "target_plan_id": "plan-bundle",
        "target_plan_digest": "a" * 64,
        "target_plan_schema_version": "1",
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
        "captured_at_utc": "2025-01-01T00:00:00Z",
    }
    case = {
        "target_id": "target-bundle",
        "attempt_id": "attempt-bundle",
        "accession": "0000000001-24-000001",
        "form": "10-K",
        "request_id": "request-bundle",
        "target_role": "primary",
        "target_type": "primary",
        "optional": 0,
        "catalog_direct_selection": "submitted_primary",
        "source_origin": "catalog_direct",
        "target_status": "matched",
        "retrieval_mode": "bundle_sequence",
        "target_url": "https://www.sec.gov/submission.txt",
        "final_url": "https://www.sec.gov/submission.txt",
        "sequence": 2,
        "acquisition_status": "acquired",
        "error_code": None,
        "response_sha256": source_digest,
        "index_response_sha256": None,
        "selected_response_sha256": None,
        "resolution_schema_version": None,
        "screen_kind": "none",
        "screen_result": "not_run",
        "evaluator_version": None,
        "index_parser_version": None,
        "matching_entry_ids_json": None,
        "selected_sequence": None,
        "selected_retrieval_mode": None,
        "selected_url": None,
        "source_byte_size": len(bundle),
        "selected_sha256": selected_digest,
        "selected_byte_size": len(selected_body),
        "selected_filename": "report.htm",
        "content_type": None,
        "content_encoding": None,
    }
    append_fixture_case(
        paths,
        "fixture-bundle",
        capture,
        case,
        io.BytesIO(bundle),
        max_response_bytes=len(bundle),
    )
    output = tmp_path / "bundle-selected.htm"

    replay = replay_fixture_case(
        "fixture-bundle",
        "capture-bundle",
        "target-bundle",
        output,
        paths=paths,
    )

    assert replay.output_path == output
    assert replay.response_sha256 == source_digest
    assert output.read_bytes() == selected_body
