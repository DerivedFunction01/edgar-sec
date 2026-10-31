import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.pipelines.document_acquisition.run_state.models import (
    WorkOrderTargetSeed,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    initialize_run_state,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    compare_work_order_seeds,
    iter_work_order_rows,
)


def _work_order(path, rows):
    pq.write_table(
        pa.table(
            {
                "target_id": [row[0] for row in rows],
                "executable": [row[1] for row in rows],
                "skip_reason": [row[2] for row in rows],
            }
        ),
        path,
    )


def test_compare_work_order_seeds_attaches_sqlite_and_checks_coverage(tmp_path):
    database = tmp_path / "state.sqlite"
    part = tmp_path / "work-order.parquet"
    rows = [
        ("first", True, None),
        ("second", False, "target_not_matched"),
    ]
    initialize_run_state(database, (WorkOrderTargetSeed(*row) for row in rows))
    _work_order(part, rows)

    assert compare_work_order_seeds(database, (part,)) == (2, 2, 0)


def test_compare_work_order_seeds_streams_fallback_without_scanner(
    tmp_path, monkeypatch
):
    from edgar_sec.pipelines.document_acquisition import run_validation

    database = tmp_path / "state.sqlite"
    part = tmp_path / "work-order.parquet"
    rows = [("first", True, None), ("second", False, "target_not_matched")]
    initialize_run_state(database, (WorkOrderTargetSeed(*row) for row in rows))
    _work_order(part, rows)
    monkeypatch.setattr(run_validation, "_sqlite_scanner_installed", lambda _: False)

    assert run_validation.compare_work_order_seeds(database, (part,)) == (2, 2, 0)


def test_iter_work_order_rows_yields_rows_in_parquet_order(tmp_path):
    part = tmp_path / "work-order.parquet"
    rows = [("second", False, "target_not_matched"), ("first", True, None)]
    _work_order(part, rows)

    streamed = iter_work_order_rows((part,))

    assert next(streamed)["target_id"] == "second"
    assert next(streamed)["target_id"] == "first"
