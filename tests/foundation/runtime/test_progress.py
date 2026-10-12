from __future__ import annotations

from edgar_sec.foundation.runtime.progress import make_tqdm_callback


class _ProgressBar:
    def __init__(self) -> None:
        self.count = 0
        self.postfix = {}

    def update(self, count: int) -> None:
        self.count += count

    def set_postfix(self, values: dict[str, int]) -> None:
        self.postfix = values


def test_tqdm_callback_accepts_aggregated_outcome_counts() -> None:
    bar = _ProgressBar()
    callback = make_tqdm_callback(bar)

    callback({"status": "ok", "count": 3})
    callback({"status": "failed", "count": 2})

    assert bar.count == 5
    assert bar.postfix == {"ok": 3, "fail": 2, "hist": 0}
