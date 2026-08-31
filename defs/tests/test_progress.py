from defs.runtime.progress import make_merge_progress_callback, make_tqdm_callback


class Bar:
    def __init__(self):
        self.updated = 0
        self.postfix = None

    def update(self, amount):
        self.updated += amount

    def set_postfix(self, value):
        self.postfix = value


def test_tqdm_callback_updates_generic_completion_metrics():
    bar = Bar()
    callback = make_tqdm_callback(bar)
    callback(
        {
            "type": "cik_done",
            "status": "ok",
            "filings": 2,
            "historical_files": 1,
            "metrics": {"requests_total": 3, "retries_used": 1},
        }
    )
    assert bar.updated == 1
    assert bar.postfix["ok"] == 1
    assert bar.postfix["hist"] == 1
    assert bar.postfix["req"] == 3
    assert bar.postfix["retry"] == 1


def test_tqdm_callback_omits_unavailable_http_metrics():
    bar = Bar()
    callback = make_tqdm_callback(bar)
    callback({"type": "document_done", "status": "ok"})

    assert bar.updated == 1
    assert bar.postfix == {"ok": 1, "fail": 0, "hist": 0}


def test_merge_callback_advances_on_stage_and_partition_events():
    bar = Bar()
    callback = make_merge_progress_callback(bar)
    callback({"type": "partition_validated", "partition_id": 1, "rows": 5})
    assert bar.updated == 1
    assert bar.postfix["rows"] == 5
    assert bar.postfix["partition"] == 1
    callback({"type": "partition_validated", "partition_id": 2, "rows": 3})
    assert bar.updated == 2
    callback({"type": "merge_stage", "stage": "publish", "rows": 8})
    assert bar.updated == 3
    assert bar.postfix["rows"] == 8
    assert bar.postfix["stage"] == "publish"
    callback({"type": "readback_done", "rows": 8})
    assert bar.updated == 3
    assert bar.postfix["rows"] == 8


def test_merge_callback_tolerates_unknown_events():
    bar = Bar()
    callback = make_merge_progress_callback(bar)
    callback({"type": "something_new"})
    callback({})
    assert bar.updated == 0
    assert bar.postfix["rows"] == 0
