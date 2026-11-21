"""Companyconcept lookups: SEC-reported values for one concept, as reported.

This is a fast-lookup and cross-check surface only: values are served exactly
as the SEC reports them and never feed the financial statements machinery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edgar_sec.domain.identity import Cik
from edgar_sec.domain.sec_urls import companyconcept_url
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.errors import PermanentHttpError, RetryExhausted

__all__ = ["ConceptResult", "fetch_concept"]


@dataclass(frozen=True, slots=True)
class ConceptResult:
    """One SEC-reported data point for a concept, with its provenance."""

    value: int | float
    unit: str
    end: str
    accession: str
    form: str
    filed: str
    fiscal_year: int | None
    fiscal_period: str
    frame: str = ""


def fetch_concept(
    cik: str | int | Cik,
    taxonomy: str,
    tag: str,
    *,
    client: SecHttpClient,
) -> tuple[ConceptResult, ...]:
    """Fetch one concept's reported values for a company; empty when absent."""
    cik_inst = cik if isinstance(cik, Cik) else Cik.from_raw(cik)
    url = companyconcept_url(cik_inst.to_10digit(), taxonomy, tag)
    try:
        payload = client.get_json(url)
    except (PermanentHttpError, RetryExhausted):
        return ()
    if not isinstance(payload, dict):
        return ()
    units = payload.get("units")
    if not isinstance(units, dict):
        return ()
    results: list[ConceptResult] = []
    for unit, points in units.items():
        if not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, dict):
                continue
            value = point.get("val")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            fiscal_year = point.get("fy")
            results.append(
                ConceptResult(
                    value=value,
                    unit=str(unit),
                    end=str(point.get("end", "")),
                    accession=str(point.get("accn", "")),
                    form=str(point.get("form", "")),
                    filed=str(point.get("filed", "")),
                    fiscal_year=fiscal_year if isinstance(fiscal_year, int) else None,
                    fiscal_period=str(point.get("fp", "")),
                    frame=str(point.get("frame", "")),
                )
            )
    return tuple(results)
