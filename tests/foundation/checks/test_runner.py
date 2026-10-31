from __future__ import annotations

from edgar_sec.foundation.checks.runner import registered, run_all


def test_registered_scanners_non_empty():
    scanners = registered()
    assert len(scanners) >= 12
    scanner_names = {s.name for s in scanners}
    assert "layer-boundary" in scanner_names
    assert "environment-access" in scanner_names


def test_run_all_returns_int():
    code = run_all()
    assert isinstance(code, int)
