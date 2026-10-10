from dataclasses import FrozenInstanceError

import pytest

from edgar_sec.pipelines.document_acquisition.models import TargetSlotResolution


def test_target_resolution_distinguishes_intent_policy_and_physical_slots() -> None:
    resolution = TargetSlotResolution(
        resolution_schema_version="1",
        resolution_id="resolution_1",
        run_id="run_1",
        target_id="target_1",
        target_role="primary",
        target_type="primary",
        selector="exact_form_with_lazy_index",
        expected_statutory_type="10-K",
        initial_sequence=1,
        index_document_type="10-K",
        index_primary_designation=True,
        initial_observed_body_type="8-K",
        screen_kind="sgml_type",
        screen_result="type_mismatch",
        evaluator_version=None,
        initial_body_sha256="a" * 64,
        index_attempt_id="attempt_index",
        index_response_sha256="b" * 64,
        index_parser_version="index-parser-v1",
        matching_entry_ids=("entry_2",),
        selected_sequence=2,
        selected_retrieval_mode="direct_url",
        selected_url="https://www.sec.gov/Archives/edgar/data/1/000000000124000001/doc.htm",
        result="recovered",
    )

    assert resolution.selector != resolution.expected_statutory_type
    assert resolution.target_role == "primary"
    assert resolution.target_type == "primary"
    assert resolution.expected_statutory_type == "10-K"
    assert resolution.index_document_type == "10-K"
    assert resolution.initial_observed_body_type == "8-K"
    assert resolution.initial_sequence == 1
    assert resolution.selected_sequence == 2
    with pytest.raises(FrozenInstanceError):
        resolution.selected_sequence = 1
