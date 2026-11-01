"""Comparison screening: index candidates for metrics and peer filings."""

from __future__ import annotations

from edgar_sec.apps.client.comparison import screen_filings, screen_peers
from edgar_sec.infra.storage.corpus_index import ConceptCoordinateRow, CorpusIndex

_CIK_A = "0000000001"
_CIK_B = "0000000002"
_ACC_A = "0000000001-24-000001"
_ACC_B = "0000000002-24-000002"


def _row(
    cik: str, accession: str, qname: str, head: str, modifiers: tuple[str, ...] = ()
) -> ConceptCoordinateRow:
    """One synthetic coordinate row."""
    return ConceptCoordinateRow(
        cik=cik,
        accession=accession,
        concept_qname=qname,
        head=head,
        modifiers=modifiers,
        residual_intent=0,
        residual_total=0,
        item_type="monetaryItemType",
    )


def _index() -> CorpusIndex:
    """An in-memory index over two synthetic filings."""
    index = CorpusIndex()
    index.replace_filing(
        (
            _row(_CIK_A, _ACC_A, "us-gaap:Revenue", "H_REVENUE"),
            _row(
                _CIK_A, _ACC_A, "us-gaap:NetIncome", "H_INCOME", ("M_NET_BOTTOMLINE",)
            ),
            _row(_CIK_A, _ACC_A, "us-gaap:Assets", "H_ASSET"),
        )
    )
    index.replace_filing(
        (
            _row(
                _CIK_B, _ACC_B, "us-gaap:Revenue", "H_REVENUE", ("M_CONTRACT_CUSTOMER",)
            ),
            _row(_CIK_B, _ACC_B, "us-gaap:Assets", "H_ASSET"),
        )
    )
    return index


def test_screen_filings_matches_the_coordinate_rule() -> None:
    """A filing is a candidate when a row sits at the metric's coordinate."""
    index = _index()
    screened = screen_filings(index, ["revenue", "net_income", "total_assets"])
    assert screened["revenue"] == ((_CIK_A, _ACC_A), (_CIK_B, _ACC_B))
    assert screened["net_income"] == ((_CIK_A, _ACC_A),)
    assert screened["total_assets"] == ((_CIK_A, _ACC_A), (_CIK_B, _ACC_B))
    index.close()


def test_screen_filings_defaults_cover_every_metric() -> None:
    """The default screen answers for all canonical metrics."""
    index = _index()
    screened = screen_filings(index)
    assert set(screened) == {
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "operating_cash_flow",
        "total_assets",
        "total_debt",
        "total_equity",
    }
    index.close()


def test_screen_peers_finds_exact_coordinate_sharing() -> None:
    """Peers share an exact coordinate; a head-only match does not count."""
    index = _index()
    assert screen_peers(index, _CIK_A, _ACC_A) == ((_CIK_B, _ACC_B),)
    assert screen_peers(index, _CIK_B, _ACC_B) == ((_CIK_A, _ACC_A),)
    index.close()
