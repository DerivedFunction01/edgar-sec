from __future__ import annotations

from pathlib import Path

import edgar_sec.tools.workers.worker_profile_probe as probe


def test_changed_case_fingerprint_does_not_keep_old_call_time() -> None:
    test_file = Path("tests/domain/test_sample.py")
    nodeid = f"{test_file.as_posix()}::test_one"
    profile = {
        "cases": {
            nodeid: {
                "fingerprint": "old",
                "call_seconds": 1.0,
            }
        }
    }

    probe._merge_case_timings(
        profile,
        [{"nodeid": nodeid, "duration": 3.0, "phases": {"call": 3.0}}],
        [test_file],
        {test_file.as_posix(): "new"},
    )

    assert profile["cases"][nodeid]["call_seconds"] == 3.0
