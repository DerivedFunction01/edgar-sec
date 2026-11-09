"""Browse-edgar company/series builders: the probed shapes are pinned."""

from __future__ import annotations

import pytest

from edgar_sec.domain.browse_urls import browse_company_url, browse_series_url
from edgar_sec.domain.sec_urls import classify_sec_surface


def test_browse_company_url_pins_the_getcompany_shape() -> None:
    expected = (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000003521"
    )
    assert browse_company_url(3521) == expected
    assert browse_company_url("0000003521") == expected


def test_browse_series_url_pins_the_scd_series_shape() -> None:
    assert browse_series_url(3521) == (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        "&CIK=0000003521&scd=series"
    )


@pytest.mark.parametrize("url", [browse_company_url(3521), browse_series_url(3521)])
def test_browse_urls_classify_to_the_browse_surface(url: str) -> None:
    assert classify_sec_surface(url) == "browse_edgar"
