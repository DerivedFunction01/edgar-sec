"""Tests for the frames client surface and its cross-check comparison."""

from __future__ import annotations

from typing import Any

from edgar_sec.apps.client.frames import (
    compare_frame_to_parsed,
    fetch_frame,
)
from edgar_sec.domain.sec_urls import frames_url
from edgar_sec.infra.sec_http.errors import PermanentHttpError
from tests.support import load_fixture


class _FakeHttp:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.calls.append(url)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_fetch_frame_maps_instant_fixture_field_for_field() -> None:
    client = _FakeHttp(load_fixture("frames_instant.json"))
    result = fetch_frame("us-gaap", "Assets", "USD", "CY2025Q4I", client=client)

    assert client.calls == [frames_url("us-gaap", "Assets", "USD", "CY2025Q4I")]
    assert result.frame.taxonomy == "us-gaap"
    assert result.frame.tag == "Assets"
    assert result.frame.unit == "USD"
    assert result.frame.period == "CY2025Q4I"
    assert result.frame.is_instant is True
    assert result.label == "Assets"
    assert len(result.rows) == 3
    first = result.rows[0]
    assert first.cik == 320193
    assert first.entity_name == "Apple Inc."
    assert first.value == 379297000000
    assert first.end == "2025-12-31"
    assert first.frame is result.frame


def test_fetch_frame_maps_duration_fixture_field_for_field() -> None:
    client = _FakeHttp(load_fixture("frames_duration.json"))
    result = fetch_frame("us-gaap", "Revenues", "USD", "CY2025Q4", client=client)

    assert result.frame.is_instant is False
    assert result.label == "Revenues"
    assert [(row.cik, row.value, row.end) for row in result.rows] == [
        (320193, 143756000000, "2025-12-31"),
        (1750, 698700000, "2025-11-30"),
    ]


def test_fetch_frame_missing_frame_is_empty() -> None:
    url = frames_url("us-gaap", "Assets", "USD", "CY1999Q4I")
    client = _FakeHttp(PermanentHttpError(url, "not found", status_code=404))
    result = fetch_frame("us-gaap", "Assets", "USD", "CY1999Q4I", client=client)
    assert result.rows == ()
    assert result.frame.period == "CY1999Q4I"


def test_fetch_frame_payload_without_data_is_empty() -> None:
    assert (
        fetch_frame("us-gaap", "Assets", "USD", "CY2025Q4I", client=_FakeHttp({})).rows
        == ()
    )
    assert (
        fetch_frame("us-gaap", "Assets", "USD", "CY2025Q4I", client=_FakeHttp([1])).rows
        == ()
    )


def test_facade_frames_uses_its_sec_client() -> None:
    from edgar_sec.apps.client.facade import Edgar

    http = _FakeHttp(load_fixture("frames_instant.json"))
    facade = Edgar(sec_client=http)
    result = facade.frames("us-gaap", "Assets", "USD", "CY2025Q4I")
    assert len(result.rows) == 3
    assert http.calls == [frames_url("us-gaap", "Assets", "USD", "CY2025Q4I")]


def test_compare_frame_to_parsed_reports_the_four_outcome_classes() -> None:
    result = fetch_frame(
        "us-gaap",
        "Assets",
        "USD",
        "CY2025Q4I",
        client=_FakeHttp(load_fixture("frames_instant.json")),
    )
    parsed = {
        320193: 379297000000.0,
        1750: 999.0,
        999999: 42.0,
    }
    comparison = compare_frame_to_parsed(result, parsed)

    assert comparison.counts == {
        "agree": 1,
        "diverge": 1,
        "frame_only": 1,
        "parsed_only": 1,
    }
    assert comparison.agreement_rate == 0.5
    by_cik = {row.cik: row for row in comparison.rows}
    assert by_cik[789019].outcome == "frame_only"
    assert by_cik[789019].parsed_value is None
    assert by_cik[999999].outcome == "parsed_only"
    assert by_cik[999999].frame_value is None


def test_compare_treats_parsed_absence_as_frame_only_not_divergence() -> None:
    result = fetch_frame(
        "us-gaap",
        "Assets",
        "USD",
        "CY2025Q4I",
        client=_FakeHttp(load_fixture("frames_instant.json")),
    )
    comparison = compare_frame_to_parsed(result, {320193: None})
    assert comparison.counts["frame_only"] == 3
    assert comparison.agreement_rate is None
