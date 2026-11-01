"""Financials core: the served machinery beneath the metric catalogue."""

from __future__ import annotations

from edgar_sec.apps.client.financials_core import FinancialsCore
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support import bundle_dir


def test_core_machinery_serves_through_the_catalogue() -> None:
    """The extracted core serves the catalogue's metrics unchanged."""
    facade = Xbrl.from_bundle(bundle_dir("msft_2024_10k"), load_domain_taxonomy())
    fin = facade.financials
    assert isinstance(fin, FinancialsCore)
    served, served_class = fin._series_served("H_REVENUE")
    assert served_class == "ANNUAL"
    assert served == fin.revenue_series
    assert served["2024"] == 245_122_000_000.0
