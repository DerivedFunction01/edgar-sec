"""Tests proving facade search ranking and subset comparison."""

from tests.apps.client.xbrl.xbrl_support import _create_xbrl_facade


def test_xbrl_search_revenue_specimens() -> None:
    """Search ranks the filed total by the ladder; the F5 burn-down is absent."""
    xbrl = _create_xbrl_facade("msft")
    result = xbrl.search("revenue")
    assert result.partial is False
    assert result.target_atom is not None
    assert result.target_atom.head == "H_REVENUE"
    by_qname = {hit.qname: hit for hit in result.hits}
    filed = by_qname["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"]
    assert (filed.tier, filed.rule, filed.modifier_distance) == (
        "near",
        "subsumption",
        3,
    )
    assert filed.hit_only == ("M_CONTRACT_CUSTOMER", "M_PRETAX", "M_TAX")
    assert filed.facts
    assert (
        "msft:ContractWithCustomerLiabilityRevenueRecognizedIncludingAdditions"
        not in by_qname
    )


def test_xbrl_search_cross_filer_qname_term() -> None:
    """One filer's concept name finds the atom-identical concept in another."""
    term = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    for firm in ("msft", "aapl"):
        result = _create_xbrl_facade(firm).search(term)
        assert result.hits[0].qname == term
        assert (result.hits[0].tier, result.hits[0].rule) == ("exact", "equality")
    cross = _create_xbrl_facade("msft").search(
        "us-gaap:ContractWithCustomerLiabilityRevenueRecognized"
    )
    top = cross.hits[0]
    assert top.qname == "us-gaap:ContractWithCustomerLiability"
    assert (top.tier, top.rule, top.modifier_distance) == ("exact", "equality", 0)
    variant = {hit.qname: hit for hit in cross.hits}[
        "msft:ContractWithCustomerLiabilityRevenueRecognizedIncludingAdditions"
    ]
    assert (variant.tier, variant.rule, variant.modifier_distance) == (
        "exact",
        "equality",
        0,
    )


def test_compare_subset_resolves_only_requested_metrics() -> None:
    """A subset compare skips unrequested standard metrics entirely."""
    msft = _create_xbrl_facade("msft")
    view = msft.compare([_create_xbrl_facade("aapl")], metrics=["revenue"])
    assert view.metric_labels[0][0] == "revenue"
    for data in view.cohort_data.values():
        assert data["revenue"] is not None
        assert "total_debt" not in data
        assert "gross_profit" not in data
        assert "operating_margin" in data
