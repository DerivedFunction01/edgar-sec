"""Domain dataclasses for SEC Form N-CEN filings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FormNCenDocument:
    """Structured domain representation of a Form N-CEN filing."""

    submission_type: str
    registrant_name: str
    directors: tuple[str, ...]
    filer_cik: str | None = None
    period_of_report: str | None = None
    file_number: str | None = None
    registrant_cik: str | None = None
    registrant_lei: str | None = None
    classification_type: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    is_first_filing: str | None = None
    is_last_filing: str | None = None
    series_count: int = 0
    custodian_count: int = 0
    pricing_service_count: int = 0


__all__ = [
    "FormNCenDocument",
]
