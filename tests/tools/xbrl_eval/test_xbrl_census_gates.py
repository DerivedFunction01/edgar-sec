"""Tests for the seeded census gate entry points."""


def test_battery_gate_baseline() -> None:
    """Pin the battery baseline: 188/188 since the F7 calc fix."""
    from edgar_sec.tools.xbrl_eval.xbrl_census_gates import run_battery_gate

    report = run_battery_gate()
    assert report.total == 188
    assert report.passed == 188
    assert report.failures == ()
