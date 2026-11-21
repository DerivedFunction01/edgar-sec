"""End-to-end integration tests for filing triad, content parsing, snapshots, and cleanup."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.forms.families.ownership.reports import OwnershipReport
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.runtime.paths import PLANS_DIR, TRANSIENT_DIR
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.writer import (
    publish_acquisition_run,
)
from tests.pipelines.document_acquisition.snapshot.test_writer import _setup_run


def test_e2e_prose_and_xml_triad_verification(tmp_path: Path) -> None:
    """Verify 10-K prose rendering, Form 4 XML extraction, and XBRL eligibility."""
    k_content = b"<html><body><h1>ITEM 1. BUSINESS</h1><p>Apple Inc.</p></body></html>"
    att_cal = FilingAttachment(
        attachment_id="2",
        document_type="EX-101.CAL",
        filename="aapl_cal.xml",
        url="https://www.sec.gov/cal.xml",
        fetcher=lambda a: b"<calculation/>",
    )
    filing_10k = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000106"),
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="10-K",
        filing_date="2023-11-03",
        primary_document_path="aapl-20230930.htm",
        primary_document_url="https://www.sec.gov/aapl.htm",
        attachments=(att_cal,),
        fetcher=lambda f: k_content,
    )

    rendered_text = filing_10k.render()
    assert rendered_text is not None
    assert filing_10k.has_xbrl is True
    assert len(filing_10k.linkbases) == 1
    assert filing_10k.open_linkbase("_cal.xml") == b"<calculation/>"

    form4_xml = (
        b'<?xml version="1.0"?>'
        b"<ownershipDocument>"
        b"<issuer><issuerCik>0000320193</issuerCik></issuer>"
        b"<nonDerivativeTransaction><transactionCoding><transactionCode>P</transactionCode></transactionCoding></nonDerivativeTransaction>"
        b"</ownershipDocument>"
    )
    xml_path = tmp_path / "form4.xml"
    xml_path.write_bytes(form4_xml)

    filing_4 = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000002"),
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="4",
        filing_date="2023-11-04",
        primary_storage_path=xml_path,
    )

    rep = filing_4.as_report()
    assert isinstance(rep, OwnershipReport)
    raw_xml = rep.xml()
    assert raw_xml is not None
    root = ET.fromstring(raw_xml)
    assert root.tag == "ownershipDocument"
    assert root.findtext("issuer/issuerCik") == "0000320193"
    assert root.findtext(".//transactionCode") == "P"
    assert filing_4.has_xbrl is False
    assert filing_4.linkbases == ()


def test_e2e_snapshot_tagging_retrieval_and_sql(tmp_path: Path) -> None:
    """Verify publishing snapshot, tagging via console, offline retrieval, and SQL."""
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")

    edgar = Edgar(artifacts_root=tmp_path)
    edgar.snapshots.tag("test-prod-v1", pub.snapshot_id)

    res = edgar.from_snapshot("test-prod-v1")
    assert len(res) == 1
    assert res.snapshot_id == pub.snapshot_id

    sql_res = res.sql(
        "SELECT c.form, i.filename FROM catalog c JOIN index i USING (accession)"
    )
    df = sql_res.df()
    assert len(df) == 1
    assert df.iloc[0]["form"] == "10-K"


def test_e2e_artifact_lifecycle_and_clearing(tmp_path: Path) -> None:
    """Verify clearing transient runs and plans via facade.clean()."""
    edgar = Edgar(artifacts_root=tmp_path)
    run_dir = tmp_path / TRANSIENT_DIR / "document_acquisition" / "run-ephemeral"
    run_dir.mkdir(parents=True)
    (run_dir / "state.sqlite").write_text("data")

    plan_dir = tmp_path / "document_planning" / PLANS_DIR / "plan-ephemeral"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text("{}")

    clean_res = edgar.clean(scope="all")
    assert clean_res["transient"] >= 1
    assert clean_res["plans"] >= 1
    assert not run_dir.exists()
    assert not plan_dir.exists()
