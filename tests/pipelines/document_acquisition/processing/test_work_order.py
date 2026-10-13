from __future__ import annotations

import sqlite3

from edgar_sec.pipelines.document_acquisition.processing.work_order import (
    operation_requests,
    resolved_operations,
    stream_resolved_operations,
)
from tests.acquisition_run_fixture import make_acquisition_run


def test_resolved_work_order_operations_round_trip(tmp_path) -> None:
    paths, run_id, target = make_acquisition_run(tmp_path / "artifacts", lazy=False)
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        stream_resolved_operations(connection, paths, run_id)
        rows = resolved_operations(connection, target["target_id"])
    finally:
        connection.close()

    operations = operation_requests(rows)
    assert {item.operation for item in operations} == {
        "raw",
        "render_to_txt",
        "render_to_xml",
    }
    assert sum(item.operation == "raw" for item in operations) == 1
