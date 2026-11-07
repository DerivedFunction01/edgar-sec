"""Tests for the companyconcept client surface."""

from __future__ import annotations

from typing import Any

from edgar_sec.apps.client.concept import fetch_concept
from edgar_sec.apps.client.entity import Company
from edgar_sec.domain.identity import Cik
from edgar_sec.domain.sec_urls import companyconcept_url
from edgar_sec.domain.submissions.models import EntityProfile
from edgar_sec.infra.sec_http.errors import PermanentHttpError

AAR = 1750


def _payload() -> dict[str, Any]:
    return {
        "cik": AAR,
        "taxonomy": "us-gaap",
        "tag": "Assets",
        "units": {
            "USD": [
                {
                    "end": "2025-12-31",
                    "val": 123456,
                    "accn": "0000001750-26-000010",
                    "fy": 2025,
                    "fp": "FY",
                    "form": "10-K",
                    "filed": "2026-02-01",
                    "frame": "CY2025Q4I",
                },
                {
                    "end": "2024-12-31",
                    "val": 100000,
                    "accn": "0000001750-25-000009",
                    "fy": 2024,
                    "fp": "FY",
                    "form": "10-K",
                    "filed": "2025-02-01",
                },
            ],
            "shares": [
                {
                    "end": "2025-12-31",
                    "val": 42,
                    "accn": "0000001750-26-000010",
                    "fy": 2025,
                    "fp": "FY",
                    "form": "10-K",
                    "filed": "2026-02-01",
                }
            ],
        },
    }


class _FakeHttp:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.calls.append(url)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_fetch_concept_serves_reported_values_with_provenance() -> None:
    client = _FakeHttp(_payload())
    results = fetch_concept(AAR, "us-gaap", "Assets", client=client)

    assert client.calls == [companyconcept_url("0000001750", "us-gaap", "Assets")]
    assert len(results) == 3
    first = results[0]
    assert first.value == 123456
    assert first.unit == "USD"
    assert first.end == "2025-12-31"
    assert first.accession == "0000001750-26-000010"
    assert first.form == "10-K"
    assert first.filed == "2026-02-01"
    assert first.fiscal_year == 2025
    assert first.fiscal_period == "FY"
    assert first.frame == "CY2025Q4I"
    assert results[1].frame == ""
    assert results[2].unit == "shares"


def test_fetch_concept_missing_concept_is_empty() -> None:
    url = companyconcept_url("0000001750", "us-gaap", "NoSuchTag")
    client = _FakeHttp(PermanentHttpError(url, "not found", status_code=404))

    assert fetch_concept(AAR, "us-gaap", "NoSuchTag", client=client) == ()


def test_fetch_concept_payload_without_units_is_empty() -> None:
    assert fetch_concept(AAR, "us-gaap", "Assets", client=_FakeHttp({})) == ()
    assert fetch_concept(AAR, "us-gaap", "Assets", client=_FakeHttp([1, 2])) == ()


def test_company_concept_uses_facade_sec_client() -> None:
    from edgar_sec.apps.client.facade import Edgar

    http = _FakeHttp(_payload())
    facade = Edgar(sec_client=http)
    company = Company(
        profile=EntityProfile(cik=Cik.from_raw(AAR), name="AAR CORP"),
        facade=facade,
    )

    results = company.concept("us-gaap", "Assets")

    assert len(results) == 3
    assert http.calls == [companyconcept_url("0000001750", "us-gaap", "Assets")]
