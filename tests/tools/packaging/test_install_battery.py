"""The install battery's bookkeeping: leg verdicts aggregate their checks,
and the probes cover the installed contract.
"""

from __future__ import annotations

from edgar_sec.tools.packaging.install_battery import LegResult


def test_a_leg_passes_only_when_every_check_passes() -> None:
    leg = LegResult(name="wheel", proves="the wheel")
    leg.check("one", True)
    assert leg.passed
    leg.check("two", False, "detail")
    assert not leg.passed
    assert leg.checks[-1] == "FAIL two detail"


def test_the_probes_cover_the_installed_contract() -> None:
    from edgar_sec.tools.packaging import install_battery

    assert "load_canonical_union_cohort" in install_battery._COHORT_PROBE
    assert "125" in install_battery._COHORT_PROBE
    assert "archived_taxonomies" in install_battery._TAXONOMY_PROBE
    assert "package_data_status" in install_battery._PRESENCE_PROBE
    assert "edgar_sec.tools" in install_battery._IMPORT_SWEEP
