"""Tests for the operator's fund series/class row and its delegation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.apps.client import operator, operator_fund
from edgar_sec.pipelines.metadata_sync.commands import series_class as commands
from edgar_sec.pipelines.metadata_sync.series_class import (
    SeriesClassPublishOutcome,
    SeriesClassReconciliation,
)


class _Facade:
    """The executor reads only ``artifacts_root`` off the facade."""

    def __init__(self, root: Path) -> None:
        self.artifacts_root = root


def _session(tmp_path: Path) -> operator.ClientSession:
    return operator.ClientSession(_Facade(tmp_path))


def _outcome(**overrides) -> commands.SeriesClassRefreshOutcome:
    values = {
        "population": 2,
        "parsed_ingested": 1,
        "parse_failures": 0,
        "unrecognized": 0,
        "fetch_failures": 1,
        "publish": SeriesClassPublishOutcome(
            published=True, snapshot_id="series-class-x", tip_before=None
        ),
        "tip_after": "series-class-x",
        "reconciliation": SeriesClassReconciliation(
            series_in_both=1,
            series_browse_only=0,
            series_file_only=1,
            classes_in_both=1,
            classes_browse_only=3,
            classes_file_only=1,
            symbol_agreements=1,
            symbol_disagreements=0,
            shared_classes_browse_untickered=0,
        ),
        "symbol_disagreement_samples": (),
        "failure_samples": (("0000009999", "fetch_failure"),),
    }
    values.update(overrides)
    return commands.SeriesClassRefreshOutcome(**values)


def test_row_is_registered_with_the_amendments_vocabulary() -> None:
    spec = operator.REGISTRY["fund_series_class"]

    assert spec.effect == "external"
    assert spec.requires == "none"
    assert spec.result_kind == "key_value"
    assert spec.options_type is operator_fund.FundSeriesClassOptions


def test_status_on_an_empty_root_is_honest_absence(tmp_path: Path) -> None:
    result = operator.execute_by_id("fund_series_class", _session(tmp_path), {})

    assert result.error_code is None
    assert result.data["action"] == "status"
    assert result.data["tip"] is None
    assert result.data["tickered_rows"] == 0
    assert not (tmp_path / "operator-runs").exists()


def test_reconcile_writes_no_run_record(tmp_path: Path) -> None:
    result = operator.execute_by_id(
        "fund_series_class", _session(tmp_path), {"action": "reconcile"}
    )

    assert result.error_code is None
    assert result.data["reconciliation"]["classes_in_both"] == 0
    assert not (tmp_path / "operator-runs").exists()


def test_unknown_action_is_invalid_options(tmp_path: Path) -> None:
    result = operator.execute_by_id(
        "fund_series_class", _session(tmp_path), {"action": "poll"}
    )

    assert result.error_code == "invalid_options"


def test_refresh_delegates_and_writes_one_run_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    def stub(**kwargs) -> commands.SeriesClassRefreshOutcome:
        calls.append(kwargs)
        return _outcome()

    monkeypatch.setattr(commands, "refresh_series_class", stub)
    session = _session(tmp_path)

    result = operator.execute_by_id(
        "fund_series_class",
        session,
        {"action": "refresh", "ciks": ["2663"], "force_refresh": True},
    )

    assert result.error_code is None
    assert calls[0]["artifacts_root"] == tmp_path
    assert calls[0]["ciks"] == ("2663",)
    assert calls[0]["force_refresh"] is True
    assert result.data["published"] is True
    assert result.data["snapshot_id"] == "series-class-x"
    assert result.data["accounting"]["fetch_failures"] == 1
    assert result.data["reconciliation"]["classes_browse_only"] == 3
    records = list((tmp_path / "operator-runs").glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["operation"] == "fund_series_class"
    assert record["record_id"] == result.data["record_id"]
    assert record["publish"]["tip_after"] == "series-class-x"
    assert record["accounting"]["population"] == 2
    assert record["error_code"] is None


def test_refresh_failure_is_coded_and_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def stub(**kwargs) -> commands.SeriesClassRefreshOutcome:
        raise RuntimeError("drive exploded")

    monkeypatch.setattr(commands, "refresh_series_class", stub)

    result = operator.execute_by_id(
        "fund_series_class", _session(tmp_path), {"action": "refresh"}
    )

    assert result.error_code == "external_failure"
    records = list((tmp_path / "operator-runs").glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["error_code"] == "external_failure"
    assert record["error"] == "drive exploded"


def test_workers_below_one_is_invalid_options(tmp_path: Path) -> None:
    result = operator.execute_by_id(
        "fund_series_class",
        _session(tmp_path),
        {"action": "refresh", "workers": 0},
    )

    assert result.error_code == "invalid_options"
