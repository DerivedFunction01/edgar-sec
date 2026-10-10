from __future__ import annotations

import sys

import pyarrow as pa

from edgar_sec.pipelines.document_acquisition.schemas import (
    ACQUISITION_CONTRACT_VERSION,
    RECEIPT_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    WORK_ORDER_SCHEMA_VERSION,
    StagedBodyRef,
    target_relation_schema,
    target_relation_schema_version,
)


def test_shared_schema_contract_versions_are_explicit() -> None:
    assert ACQUISITION_CONTRACT_VERSION == "1"
    assert RECEIPT_SCHEMA_VERSION == "1"
    assert RUN_SCHEMA_VERSION == "1"
    assert WORK_ORDER_SCHEMA_VERSION == "1"


def test_s6_relation_contract_load_is_deferred() -> None:
    module = sys.modules["edgar_sec.pipelines.document_acquisition.schemas"]
    assert not hasattr(module, "pa")
    schema = target_relation_schema()
    assert isinstance(schema, pa.Schema)
    assert schema.names[0] == "target_id"
    assert target_relation_schema_version() == 1


def test_staged_body_ref_keeps_source_and_selected_identity_separate(tmp_path) -> None:
    selected = tmp_path / "selected.htm"
    source = tmp_path / "response.txt"
    body = StagedBodyRef(
        run_id="run_1",
        target_id="target_1",
        path=selected,
        sha256="a" * 64,
        byte_size=12,
        selected_filename="primary.htm",
        source_response_path=source,
        source_response_sha256="b" * 64,
        source_response_byte_size=80,
    )

    assert body.path != body.source_response_path
    assert body.sha256 != body.source_response_sha256
    assert body.byte_size != body.source_response_byte_size
