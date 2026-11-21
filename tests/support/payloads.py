"""SEC submissions URL and payload builders for tests."""

from __future__ import annotations

from typing import Any

from edgar_sec.domain.sec_urls import historical_submissions_url, submissions_url


def submissions_document(cik_padded: str) -> str:
    return submissions_url(cik_padded)


def historical_url(name: str) -> str:
    return historical_submissions_url(name)


def cik_payload(cik: str, name: str, accession: str | None = None) -> dict[str, Any]:
    """A well-formed row is enough here; golden replay tests use the real fixtures."""
    accession = accession or f"{cik}-26-000001"
    return {
        "name": name,
        "filings": {
            "recent": {
                "accessionNumber": [accession],
                "filingDate": ["2026-01-02"],
                "form": ["10-K"],
                "size": [1024],
            },
            "files": [],
        },
    }


__all__ = [
    "cik_payload",
    "historical_url",
    "submissions_document",
]
