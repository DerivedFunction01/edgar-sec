import pytest

from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths


@pytest.fixture
def acquisition_paths(tmp_path):
    return resolve_acquisition_paths(artifacts_root=tmp_path)


@pytest.fixture
def capture_values():
    return {
        "capture_id": "capture_1",
        "run_id": "run_1",
        "target_plan_id": "plan_1",
        "target_plan_digest": "a" * 64,
        "target_plan_schema_version": "1",
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
        "captured_at_utc": "2026-10-10T00:00:00Z",
    }


@pytest.fixture
def case_factory():
    def make_case(target_id="target_1"):
        return {
            "target_id": target_id,
            "attempt_id": f"attempt_{target_id}",
            "accession": "0000000001-24-000001",
            "form": "10-K",
            "request_id": "request_1",
            "target_role": "primary",
            "target_type": "primary",
            "optional": 0,
            "catalog_direct_selection": "submitted_primary",
            "source_origin": "catalog_direct",
            "target_status": "matched",
            "retrieval_mode": "direct_url",
            "target_url": "https://www.sec.gov/document.htm",
            "final_url": "https://www.sec.gov/document.htm",
            "sequence": None,
            "acquisition_status": "acquired",
            "error_code": None,
            "response_sha256": None,
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
            "source_byte_size": None,
            "selected_sha256": None,
            "selected_byte_size": None,
            "selected_filename": "document.htm",
            "content_type": "text/html",
            "content_encoding": None,
        }

    return make_case
