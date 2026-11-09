"""Tests for the drill-down exhibits module's registry contribution."""

from __future__ import annotations

from edgar_sec.apps.client import operator, operator_drill_exhibits


def test_exhibits_module_rows_register_with_gates() -> None:
    specs = {spec.id: spec for spec in operator_drill_exhibits.build_specs()}
    assert set(specs) == {
        "exhibits_list",
        "read_exhibit",
        "xbrl_summary",
        "earnings_exhibit",
        "save_payload",
        "save_bundle",
    }
    for spec in specs.values():
        assert spec.requires == "current_filing"
        assert operator.REGISTRY[spec.id] is not None
    assert specs["xbrl_summary"].available is not None
    assert specs["earnings_exhibit"].available is not None
    assert specs["exhibits_list"].available is None
    assert specs["save_payload"].effect == "external"


def test_exhibits_module_gatherers_cover_rows() -> None:
    assert set(operator_drill_exhibits.GATHERERS) == {
        "exhibits_list",
        "read_exhibit",
        "xbrl_summary",
        "earnings_exhibit",
        "save_payload",
        "save_bundle",
    }
