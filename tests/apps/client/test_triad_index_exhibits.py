"""Tests for filing triad (catalog, index, payload), safe exhibits, and DataFrame shapes."""

from __future__ import annotations

from pathlib import Path
import pytest

from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik


def test_form4_has_no_xbrl_and_fails_closed(tmp_path: Path) -> None:
    """Verify non-XBRL Form 4 returns has_xbrl=False and linkbases=() without network."""
    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000001"),
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="4",
        filing_date="2023-01-15",
    )
    assert filing.has_xbrl is False
    assert filing.linkbases == ()
    with pytest.raises(FileNotFoundError, match="no linkbase matching '_cal.xml'"):
        filing.open_linkbase("_cal.xml")


def test_10k_exhibit_and_linkbase_discovery() -> None:
    """Verify 10-K exhibit and linkbase properties and safe exhibit lookup."""
    att1 = FilingAttachment(
        attachment_id="1",
        document_type="10-K",
        filename="aapl-20230930.htm",
        url="https://www.sec.gov/.../aapl.htm",
    )
    att2 = FilingAttachment(
        attachment_id="2",
        document_type="EX-21.1",
        filename="aapl_ex21.htm",
        description="SUBSIDIARIES",
        url="https://www.sec.gov/.../ex21.htm",
        size=45020,
    )
    att3 = FilingAttachment(
        attachment_id="3",
        document_type="EX-101.CAL",
        filename="aapl_cal.xml",
        url="https://www.sec.gov/.../cal.xml",
        size=120400,
        fetcher=lambda a: b"<calculation/>",
    )

    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000106"),
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="10-K",
        filing_date="2023-11-03",
        report_date="2023-09-30",
        primary_document_url="https://www.sec.gov/.../aapl.htm",
        attachments=(att1, att2, att3),
    )

    assert filing.has_xbrl is True
    assert len(filing.exhibits) >= 1
    assert filing.exhibit("21") == att2
    assert filing.exhibit("EX-21.1") == att2
    assert filing.exhibit("99") is None

    assert len(filing.linkbases) == 1
    assert filing.linkbases[0] == att3
    data = filing.open_linkbase("_cal.xml")
    assert data == b"<calculation/>"


def test_six_dataframe_shapes_and_sql(tmp_path: Path) -> None:
    """Verify all 6 DataFrame export shapes and multi-view DuckDB SQL auto-binding."""
    att1 = FilingAttachment(
        attachment_id="1",
        document_type="10-K",
        filename="aapl-20230930.htm",
        url="https://www.sec.gov/.../aapl.htm",
    )
    att2 = FilingAttachment(
        attachment_id="2",
        document_type="EX-21.1",
        filename="aapl_ex21.htm",
        description="SUBSIDIARIES",
        url="https://www.sec.gov/.../ex21.htm",
        size=45020,
    )
    att3 = FilingAttachment(
        attachment_id="3",
        document_type="EX-101.CAL",
        filename="aapl_cal.xml",
        url="https://www.sec.gov/.../cal.xml",
    )

    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000106"),
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="10-K",
        filing_date="2023-11-03",
        report_date="2023-09-30",
        primary_document_url="https://www.sec.gov/.../aapl.htm",
        attachments=(att1, att2, att3),
    )

    res = FilingsResult(
        run_id="run-1",
        plan_id="plan-1",
        target_parquet_glob="",
        run_state_sqlite_path=tmp_path / "dummy.sqlite",
        artifacts_root=tmp_path,
        items=(filing,),
    )

    df_cat = res.to_df()
    assert list(df_cat.columns) == [
        "accession",
        "form",
        "filing_date",
        "report_date",
        "primary_document",
        "primary_doc_url",
    ]
    assert len(df_cat) == 1

    df_idx = res.attachments_df()
    assert list(df_idx.columns) == [
        "accession",
        "sequence",
        "document_type",
        "filename",
        "description",
        "size",
        "url",
        "is_exhibit",
    ]
    assert len(df_idx) == 3

    df_ex = res.exhibits()
    assert list(df_ex.columns) == [
        "accession",
        "form",
        "document_type",
        "description",
        "filename",
        "size",
        "url",
    ]
    assert len(df_ex) >= 1

    df_lb = res.linkbases_df()
    assert list(df_lb.columns) == [
        "accession",
        "form",
        "linkbase_type",
        "document_type",
        "filename",
        "url",
    ]
    assert len(df_lb) == 1
    assert df_lb.iloc[0]["linkbase_type"] == "calculation"

    df_stg = res.staged_df()
    assert list(df_stg.columns) == [
        "target_id",
        "accession",
        "outcome",
        "attempt_count",
        "duration_ms",
        "body_sha256",
        "body_byte_size",
        "body_storage_path",
    ]
    assert len(df_stg) == 1

    df_join = res.joined_df()
    assert list(df_join.columns) == [
        "accession",
        "form",
        "filing_date",
        "primary_document",
        "outcome",
        "body_byte_size",
        "body_storage_path",
        "target_url",
    ]
    assert len(df_join) == 1

    sql_res = res.sql(
        "SELECT c.form, i.filename FROM catalog c JOIN index i USING (accession) WHERE i.is_exhibit = true"
    )
    sql_df = sql_res.df()
    assert len(sql_df) >= 1
    assert sql_df.iloc[0]["form"] == "10-K"
