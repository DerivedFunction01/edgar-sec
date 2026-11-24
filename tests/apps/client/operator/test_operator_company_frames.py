"""Tests for the operator's frames cross-check row."""

from __future__ import annotations

from edgar_sec.apps.client.operator import operator, operator_run_records
from edgar_sec.apps.client.reference.frames import FrameIdentity, FrameResult
from tests.apps.client.operator.test_operator_company import _session


def test_frames_labelled_cross_check_and_recorded(tmp_path) -> None:
    session, _ = _session(tmp_path)
    options = {
        "taxonomy": "us-gaap",
        "tag": "Assets",
        "unit": "USD",
        "period": "CY2024Q4I",
        "limit": 2,
    }
    result = operator.execute_by_id("frames", session, options)
    assert result.error_code is None
    assert "cross-check" in result.title
    assert result.data["cross_check"] is True
    assert result.data["provenance"] == "SEC frame aggregates"
    assert (result.total, result.shown) == (3, 2)
    records = operator_run_records.list_records(session)
    assert len(records) == 1
    assert records[0]["operation"] == "frames"
    assert records[0]["selection"]["tag"] == "Assets"


def test_frames_absent_frame_is_honest_absence(tmp_path) -> None:
    session, facade = _session(tmp_path)
    facade.frame_result = FrameResult(
        frame=FrameIdentity("us-gaap", "Assets", "USD", "CY2024Q4I"),
        label="",
        rows=(),
    )
    options = {
        "taxonomy": "us-gaap",
        "tag": "Assets",
        "unit": "USD",
        "period": "CY2024Q4I",
    }
    result = operator.execute_by_id("frames", session, options)
    assert result.error_code == "absent"
    assert result.data["present"] is False
    assert "cross-check" in result.title


def test_frames_needs_explicit_coordinates(tmp_path) -> None:
    session, _ = _session(tmp_path)
    result = operator.execute_by_id("frames", session, {"taxonomy": "us-gaap"})
    assert result.error_code == "invalid_options"
    assert operator_run_records.list_records(session) == []
