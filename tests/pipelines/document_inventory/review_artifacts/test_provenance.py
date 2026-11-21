from edgar_sec.pipelines.document_inventory.review_artifacts.provenance import (
    form_lookup_for_review_records,
)


def test_form_lookup_without_artifact_root_is_empty() -> None:
    assert form_lookup_for_review_records([], None) == {}
