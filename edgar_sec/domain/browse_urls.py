"""SEC browse-edgar company and series page URL construction.

The company page and its series/class list share one CGI path; the list
is selected by the ``scd=series`` parameter the company page itself links.
"""

from __future__ import annotations

from urllib.parse import urlencode

from edgar_sec.domain.sec_urls import SEC_BROWSE_EDGAR_URL, normalize_cik


def browse_company_url(cik: str | int) -> str:
    """Return the browse-edgar company page URL for one registrant."""
    params = [("action", "getcompany"), ("CIK", normalize_cik(cik))]
    return f"{SEC_BROWSE_EDGAR_URL}?{urlencode(params)}"


def browse_series_url(cik: str | int) -> str:
    """Return the browse-edgar series/class list URL for one registrant."""
    params = [
        ("action", "getcompany"),
        ("CIK", normalize_cik(cik)),
        ("scd", "series"),
    ]
    return f"{SEC_BROWSE_EDGAR_URL}?{urlencode(params)}"


__all__ = [
    "browse_company_url",
    "browse_series_url",
]
