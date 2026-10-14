"""Tests for PlanFilterOptions serialization and defaults."""

from __future__ import annotations

from edgar_sec.domain.filing_catalog.options import PlanFilterOptions


def test_plan_filter_options_defaults() -> None:
    options = PlanFilterOptions()
    assert options.forms == ()
    assert options.xbrl_only is False
    req = options.to_request_dict()
    assert req["forms"] == []
    assert req["xbrl_only"] is False


def test_plan_filter_options_custom() -> None:
    options = PlanFilterOptions(forms=("10-K",), xbrl_only=True, limit=10)
    assert options.forms == ("10-K",)
    assert options.xbrl_only is True
    req = options.to_request_dict()
    assert req["forms"] == ["10-K"]
    assert req["xbrl_only"] is True
    assert req["limit"] == 10
