"""Corpus index store: coordinate rows persist, replace, and screen."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.infra.storage.corpus_index import ConceptCoordinateRow, CorpusIndex

_CIK_A = "0000000001"
_CIK_B = "0000000002"
_ACC_A = "0000000001-24-000001"
_ACC_B = "0000000002-24-000002"


def _row(
    cik: str,
    accession: str,
    qname: str,
    head: str,
    modifiers: tuple[str, ...] = (),
    item_type: str | None = "monetaryItemType",
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
        item_type=item_type,
    )


def _index(tmp_path: Path) -> CorpusIndex:
    """A file-backed index under the test's tmp dir."""
    return CorpusIndex(tmp_path / "index.duckdb")


def test_replace_and_read_back(tmp_path: Path) -> None:
    """Rows round-trip with modifiers ordered and item type nullable."""
    index = _index(tmp_path)
    rows = (
        _row(_CIK_A, _ACC_A, "us-gaap:Assets", "H_ASSET", (), None),
        _row(_CIK_A, _ACC_A, "us-gaap:Revenue", "H_REVENUE", ("M_PRETAX", "M_TAX")),
    )
    assert index.replace_filing(rows) == 2
    assert index.rows_for_filing(_CIK_A, _ACC_A) == rows
    assert index.row_count() == 2
    assert index.filing_count() == 1
    index.close()


def test_replace_filing_replaces_the_filings_rows(tmp_path: Path) -> None:
    """Re-ingest drops the filing's stale concepts, keeping other filings."""
    index = _index(tmp_path)
    index.replace_filing((_row(_CIK_A, _ACC_A, "us-gaap:Old", "H_REVENUE"),))
    index.replace_filing((_row(_CIK_B, _ACC_B, "us-gaap:Other", "H_ASSET"),))
    index.replace_filing((_row(_CIK_A, _ACC_A, "us-gaap:New", "H_INCOME"),))
    assert [r.concept_qname for r in index.rows_for_filing(_CIK_A, _ACC_A)] == [
        "us-gaap:New"
    ]
    assert index.row_count() == 2
    assert index.filing_count() == 2
    index.close()


def test_replace_filing_refuses_mixed_and_empty_batches(tmp_path: Path) -> None:
    """A filing is the unit of replacement: mixed or empty batches refuse."""
    index = _index(tmp_path)
    with pytest.raises(ValueError):
        index.replace_filing(())
    with pytest.raises(ValueError):
        index.replace_filing(
            (
                _row(_CIK_A, _ACC_A, "us-gaap:A", "H_REVENUE"),
                _row(_CIK_B, _ACC_B, "us-gaap:B", "H_REVENUE"),
            )
        )
    index.close()


def test_rows_for_heads_filters_and_orders(tmp_path: Path) -> None:
    """Head screening returns matching rows in (cik, accession, qname) order."""
    index = _index(tmp_path)
    index.replace_filing(
        (
            _row(_CIK_B, _ACC_B, "us-gaap:Revenue", "H_REVENUE"),
            _row(_CIK_B, _ACC_B, "us-gaap:Assets", "H_ASSET"),
        )
    )
    index.replace_filing((_row(_CIK_A, _ACC_A, "us-gaap:Revenue", "H_REVENUE"),))
    hits = index.rows_for_heads(("H_REVENUE",))
    assert [(r.cik, r.concept_qname) for r in hits] == [
        (_CIK_A, "us-gaap:Revenue"),
        (_CIK_B, "us-gaap:Revenue"),
    ]
    assert index.rows_for_heads(()) == ()
    assert index.rows_for_heads(("H_MISSING",)) == ()
    index.close()


def test_rows_at_coordinate_uses_the_superset_rule(tmp_path: Path) -> None:
    """A row matches when its modifiers cover the requested coordinate."""
    index = _index(tmp_path)
    index.replace_filing(
        (
            _row(_CIK_A, _ACC_A, "us-gaap:Net", "H_INCOME", ("M_NET_BOTTOMLINE",)),
            _row(
                _CIK_A,
                _ACC_A,
                "us-gaap:NetTax",
                "H_INCOME",
                ("M_NET_BOTTOMLINE", "M_TAX"),
            ),
            _row(_CIK_A, _ACC_A, "us-gaap:Gross", "H_INCOME", ("M_GROSS",)),
        )
    )
    hits = index.rows_at_coordinate("H_INCOME", ("M_NET_BOTTOMLINE",))
    assert [r.concept_qname for r in hits] == ["us-gaap:Net", "us-gaap:NetTax"]
    assert len(index.rows_at_coordinate("H_INCOME", ())) == 3
    assert index.rows_at_coordinate("H_REVENUE", ()) == ()
    index.close()


def test_peer_filings_share_exact_coordinates_only(tmp_path: Path) -> None:
    """Peers share a head and the full modifier set, never the filing itself."""
    index = _index(tmp_path)
    index.replace_filing(
        (
            _row(_CIK_A, _ACC_A, "us-gaap:Assets", "H_ASSET"),
            _row(_CIK_A, _ACC_A, "us-gaap:Revenue", "H_REVENUE"),
        )
    )
    index.replace_filing(
        (
            _row(_CIK_B, _ACC_B, "us-gaap:Assets", "H_ASSET"),
            _row(_CIK_B, _ACC_B, "us-gaap:Revenue", "H_REVENUE", ("M_TAX",)),
        )
    )
    assert index.peer_filings(_CIK_A, _ACC_A) == ((_CIK_B, _ACC_B),)
    index.close()


def test_index_persists_across_reopen(tmp_path: Path) -> None:
    """A file-backed index keeps its rows across connections."""
    path = tmp_path / "index.duckdb"
    index = CorpusIndex(path)
    index.replace_filing((_row(_CIK_A, _ACC_A, "us-gaap:Assets", "H_ASSET"),))
    index.close()
    reopened = CorpusIndex(path)
    assert reopened.row_count() == 1
    assert reopened.rows_for_filing(_CIK_A, _ACC_A)[0].head == "H_ASSET"
    reopened.close()


def test_failed_replace_rolls_back_to_the_prior_rows(tmp_path: Path) -> None:
    """A statement failure mid-transaction leaves the filing's old rows intact
    and the connection usable — the DuckDB 2.0 transaction-discipline pin."""
    index = _index(tmp_path)
    original = (_row(_CIK_A, _ACC_A, "us-gaap:Assets", "H_ASSET"),)
    index.replace_filing(original)
    connection = index._con

    class _FailOnInsert:
        def execute(self, query, *args):  # noqa: ANN001, ANN202
            return connection.execute(query, *args)

        def executemany(self, query, *args):  # noqa: ANN001, ANN202
            raise RuntimeError("injected insert failure")

        def __getattr__(self, name):  # noqa: ANN001, ANN204
            return getattr(connection, name)

    index._con = _FailOnInsert()
    with pytest.raises(RuntimeError, match="injected insert failure"):
        index.replace_filing((_row(_CIK_A, _ACC_A, "us-gaap:New", "H_NEW"),))
    index._con = connection
    assert index.rows_for_filing(_CIK_A, _ACC_A) == original
    assert index.replace_filing((_row(_CIK_A, _ACC_A, "us-gaap:New", "H_NEW"),)) == 1
    index.close()
