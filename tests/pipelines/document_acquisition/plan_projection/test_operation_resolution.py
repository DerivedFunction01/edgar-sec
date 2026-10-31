from edgar_sec.pipelines.document_acquisition.plan_projection.operation_resolution import (
    resolve_operation_group,
)


def test_resolves_pins_and_selects_best_requested_default_candidate():
    target = {
        "target_id": "target-1",
        "form": "10-K",
        "target_role": "primary",
        "target_type": "primary",
    }
    operations = [
        {
            "operation_id": f"op-{name}",
            "target_id": target["target_id"],
            "operation": name,
            "requested": name != "raw",
            "request_mode": "default_candidate" if name != "raw" else "mandatory_raw",
        }
        for name in ("raw", "render_to_txt", "render_to_xml")
    ]
    operations[0]["requested"] = True
    inputs = [
        {
            "operation_id": row["operation_id"],
            "input_ordinal": 0,
            "source_request_id": "source-1",
            "input_role": "selected_target_body",
        }
        for row in operations
        if row["requested"]
    ]

    resolved = resolve_operation_group(
        target,
        operations,
        {
            "source_request_id": "source-1",
            "canonical_path": "primary-document.htm",
        },
        inputs,
    )

    by_name = {row["operation"]: row for row in resolved}
    assert by_name["raw"]["selected"]
    assert by_name["raw"]["handler_id"] == "raw_identity"
    assert by_name["render_to_txt"]["support_status"] == "supported"
    assert by_name["render_to_txt"]["selected"]
    assert by_name["render_to_xml"]["support_status"] == "unsupported"
    assert not by_name["render_to_xml"]["selected"]
    assert by_name["render_to_txt"]["source_request_id"] == "source-1"
    assert by_name["render_to_txt"]["input_role"] == "selected_target_body"


def test_unrequested_operation_does_not_resolve_a_handler():
    target = {
        "target_id": "target-1",
        "form": "10-K",
        "target_role": "primary",
        "target_type": "primary",
    }
    operations = [
        {
            "operation_id": f"op-{name}",
            "target_id": target["target_id"],
            "operation": name,
            "requested": name == "raw",
            "request_mode": "mandatory_raw" if name == "raw" else "not_requested",
        }
        for name in ("raw", "render_to_txt", "render_to_xml")
    ]
    source = {"source_request_id": "source-1", "canonical_path": "body.htm"}
    resolved = resolve_operation_group(
        target,
        operations,
        source,
        [
            {
                "operation_id": operations[0]["operation_id"],
                "input_ordinal": 0,
                "source_request_id": "source-1",
                "input_role": "selected_target_body",
            }
        ],
    )

    text = next(row for row in resolved if row["operation"] == "render_to_txt")
    assert text["support_status"] == "not_evaluated"
    assert text["support_reason"] is None
    assert text["capability_id"] is None
    assert not text["selected"]
