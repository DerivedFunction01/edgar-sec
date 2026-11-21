"""BAC longitudinal era differences over the seed fixtures."""

from __future__ import annotations

from edgar_sec.engine.xbrl.solve.core.query import QueryMode, QueryStatus
from tests.support.corpus import bundle_text

from tests.engine.xbrl.solve.grounded_seed_support import (
    _BAC_ACC_2011,
    _BAC_ACC_2024,
    _BAC_CASH_2011,
    _BAC_CASH_2024,
    _bac_query,
)

from .conftest import load_seed_calculation_arcs, load_seed_facts


def test_bac_longitudinal_cash_spine_switches_concept_at_asu_boundary() -> None:
    """BAC cash spine: predecessor concept REPORTED in 2011, ASU 2016-18
    rollup REPORTED in 2024; each era's concept is absent in the other."""
    pre = _bac_query(_BAC_CASH_2011, _BAC_ACC_2011, "2011-12-31", "bac_2011_10k")
    assert pre.status == QueryStatus.REPORTED
    assert pre.value == 120_102_000_000.0
    post_in_pre = _bac_query(
        _BAC_CASH_2024, _BAC_ACC_2011, "2011-12-31", "bac_2011_10k"
    )
    assert post_in_pre.status == QueryStatus.UNAVAILABLE
    post = _bac_query(_BAC_CASH_2024, _BAC_ACC_2024, "2024-12-31", "bac_2024_10k")
    assert post.status == QueryStatus.REPORTED
    assert post.value == 290_114_000_000.0
    pre_in_post = _bac_query(
        _BAC_CASH_2011, _BAC_ACC_2024, "2024-12-31", "bac_2024_10k"
    )
    assert pre_in_post.status == QueryStatus.UNAVAILABLE
    lines_2011 = bundle_text("bac_2011_10k").splitlines()
    assert "Cash and cash equivalents" in lines_2011[7044]
    assert "120,102" in lines_2011[7044]
    lines_2024 = bundle_text("bac_2024_10k").splitlines()
    assert "Cash and cash equivalents" in lines_2024[4563]
    assert "290,114" in lines_2024[4563]


def test_bac_cash_spine_verify_derivation_keeps_the_reported_anchor() -> None:
    """The FY2011 VERIFY_DERIVATION artefact is adjudicated in the WS1
    batch log; the spine assertion is the REPORTED anchor it carries."""
    result = _bac_query(
        _BAC_CASH_2011,
        _BAC_ACC_2011,
        "2011-12-31",
        "bac_2011_10k",
        mode=QueryMode.VERIFY_DERIVATION,
    )
    assert result.reported_fact is not None
    assert result.reported_fact.value == 120_102_000_000.0


def test_bac_parent_slice_era_difference() -> None:
    """Parent cash slice: 2011 extension concept on dei:LegalEntityAxis;
    2024 carrying-value concept only on the srt consolidated axis."""
    facts_2011 = load_seed_facts("bac_2011_10k")
    extension = [
        fact
        for fact in facts_2011
        if fact.concept_qname == "bac:CashHeldAtBankSubsidiaries"
        and fact.instant_date == "2011-12-31"
    ]
    assert len(extension) == 1
    assert extension[0].value == 124_991_000_000.0
    assert extension[0].dimensions == {"dei:LegalEntityAxis": "us-gaap:ParentMember"}
    carrying_2011 = [
        fact for fact in facts_2011 if fact.concept_qname == _BAC_CASH_2011
    ]
    assert len(carrying_2011) == 4
    assert all(not fact.dimensions for fact in carrying_2011)
    lines_2011 = bundle_text("bac_2011_10k").splitlines()
    assert "Cash held at bank subsidiaries" in lines_2011[12880]
    assert "124,991" in lines_2011[12880]

    facts_2024 = load_seed_facts("bac_2024_10k")
    assert not any(
        fact.concept_qname == "bac:CashHeldAtBankSubsidiaries" for fact in facts_2024
    )
    carrying_2024 = [
        fact for fact in facts_2024 if fact.concept_qname == _BAC_CASH_2011
    ]
    assert len(carrying_2024) == 2
    assert all(
        fact.dimensions == {"srt:ConsolidatedEntitiesAxis": "srt:ParentCompanyMember"}
        for fact in carrying_2024
    )
    parent_2024 = next(
        fact for fact in carrying_2024 if fact.instant_date == "2024-12-31"
    )
    assert parent_2024.value == 4_613_000_000.0
    lines_2024 = bundle_text("bac_2024_10k").splitlines()
    assert "Cash held at bank subsidiaries" in lines_2024[9536]
    assert "4,613" in lines_2024[9536]


def test_bac_interest_bearing_deposits_era_role_difference() -> None:
    """InterestBearingDepositsInBanks: sibling face line in 2011 with no
    calc relation to cash; rollup component under the 2024 rollup."""
    deposits = "us-gaap:InterestBearingDepositsInBanks"
    result_2011 = _bac_query(deposits, _BAC_ACC_2011, "2011-12-31", "bac_2011_10k")
    assert result_2011.status == QueryStatus.REPORTED
    assert result_2011.value == 26_004_000_000.0
    arcs_2011 = load_seed_calculation_arcs("bac_2011_10k")
    assert not any(arc.parent_qname == _BAC_CASH_2011 for arc in arcs_2011)
    assert not any(
        arc.parent_qname == _BAC_CASH_2011 and arc.child_qname == deposits
        for arc in arcs_2011
    )
    lines_2011 = bundle_text("bac_2011_10k").splitlines()
    assert "Time deposits placed" in lines_2011[7045]
    assert "26,004" in lines_2011[7045]

    arcs_2024 = load_seed_calculation_arcs("bac_2024_10k")
    children = {
        arc.child_qname: arc.weight
        for arc in arcs_2024
        if arc.parent_qname == _BAC_CASH_2024
    }
    assert children == {"us-gaap:CashAndDueFromBanks": 1.0, deposits: 1.0}
    due = _bac_query(
        "us-gaap:CashAndDueFromBanks", _BAC_ACC_2024, "2024-12-31", "bac_2024_10k"
    )
    component = _bac_query(deposits, _BAC_ACC_2024, "2024-12-31", "bac_2024_10k")
    assert due.value == 26_003_000_000.0
    assert component.value == 264_111_000_000.0
    assert due.value + component.value == 290_114_000_000.0
