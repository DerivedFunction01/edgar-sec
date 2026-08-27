from defs.runtime.progress import make_tqdm_callback


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
