"""Smoke tests for end-to-end execution, exhibit targeting, and XML extraction."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.runner.config import RunnerOptions, TargetSpec
from edgar_sec.apps.runner.coordinator import PipelineRunner
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.forms.families.ownership.reports import OwnershipReport
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.pipelines.document_planning.profiles import get_or_create_exhibit_profile


def test_smoke_1_exhibit_targeting_resolves_profile(tmp_path: Path) -> None:
    runner = PipelineRunner(RunnerOptions(artifacts_root=tmp_path))
    profile_id = runner._resolve_profile_id(TargetSpec(role="EX-21"))
    assert profile_id == "exhibit-ex-21"

    profile = get_or_create_exhibit_profile("EX-21", profiles_root=tmp_path)
    assert profile.profile_id == "exhibit-ex-21"
    target_roles = [t.role for rule in profile.rules for t in rule.targets]
    target_types = [t.type for rule in profile.rules for t in rule.targets]
    assert "exhibit" in target_roles
    assert "EX-21" in target_types


def test_smoke_2_structured_xml_extraction_on_ownership_form(tmp_path: Path) -> None:
    xml_content = (
        b'<?xml version="1.0"?>'
        b"<ownershipDocument>"
        b"<issuer><issuerCik>0000109694</issuerCik><issuerName>TEST CORP</issuerName></issuer>"
        b"</ownershipDocument>"
    )
    xml_file = tmp_path / "primary_form4.xml"
    xml_file.write_bytes(xml_content)

    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0001181431-05-056000"),
        primary_cik=Cik(109694),
        ciks=(Cik(109694),),
        form="4",
        filing_date="2005-09-15",
        primary_storage_path=xml_file,
    )
    report = filing.as_report()

    assert isinstance(report, OwnershipReport)
    extracted_xml = report.xml()
    assert extracted_xml is not None
    root = ET.fromstring(extracted_xml)
    assert root.tag == "ownershipDocument"
    assert root.findtext("issuer/issuerName") == "TEST CORP"


def test_smoke_3_client_fetch_end_to_end_mocked(monkeypatch, tmp_path: Path) -> None:
    edgar = Edgar(artifacts_root=tmp_path)

    import pyarrow as pa
    import pyarrow.parquet as pq
    from edgar_sec.apps.client.models import FilingsResult

    parquet_path = tmp_path / "targets.parquet"
    table = pa.Table.from_arrays(
        [
            pa.array(["0001181431-05-056000"]),
            pa.array(["4"]),
            pa.array(["2005-09-15"]),
            pa.array(
                [
                    "https://www.sec.gov/Archives/edgar/data/109694/000118143105056000/form4.xml"
                ]
            ),
            pa.array(["matched"]),
        ],
        names=["accession", "form", "filing_date", "target_url", "status"],
    )
    pq.write_table(table, parquet_path)

    expected_result = FilingsResult(
        run_id="run-smoke-1",
        plan_id="plan-smoke-1",
        target_parquet_glob=str(parquet_path),
        run_state_sqlite_path=tmp_path / "state.sqlite",
        artifacts_root=tmp_path,
        snapshot_id="snap-smoke-1",
    )

    monkeypatch.setattr(
        "edgar_sec.apps.runner.coordinator.PipelineRunner.run",
        lambda self, spec: expected_result,
    )

    res = edgar.fetch(forms=["4"], ciks=["109694"], operation="auto")
    assert res.run_id == "run-smoke-1"
    assert res.snapshot_id == "snap-smoke-1"
    df = res.to_df()
    assert len(df) == 1
    assert df["form"].iloc[0] == "4"
