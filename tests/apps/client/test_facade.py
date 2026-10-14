"""Tests for Edgar facade and FilingsResult DataFrame collection."""

from __future__ import annotations

from pathlib import Path
import pyarrow as pa
import pytest

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.runner.config import TargetSpec


def test_edgar_facade_builds_specs_and_delegates(monkeypatch) -> None:
    edgar = Edgar()
    captured_specs = []

    def fake_run(self, spec: TargetSpec):
        captured_specs.append(spec)
        return "mock_result"

    monkeypatch.setattr(
        "edgar_sec.apps.runner.coordinator.PipelineRunner.run", fake_run
    )

    result = edgar.fetch(forms=["4", "3"], ciks=["109694"], dates="2024", limit=50)

    assert result == "mock_result"
    assert len(captured_specs) == 1
    assert captured_specs[0].forms == ("4", "3")
    assert captured_specs[0].ciks == ("109694",)
    assert captured_specs[0].dates == "2024"
    assert captured_specs[0].limit == 50


def test_edgar_fetch_from_file(monkeypatch, tmp_path) -> None:
    edgar = Edgar()
    captured_specs = []

    def fake_run(self, spec: TargetSpec):
        captured_specs.append(spec)
        return "file_result"

    monkeypatch.setattr(
        "edgar_sec.apps.runner.coordinator.PipelineRunner.run", fake_run
    )

    csv_file = tmp_path / "targets.csv"
    csv_file.write_text("accession\n0001-01-01\n", encoding="utf-8")

    result = edgar.fetch_from_file(csv_file, operation="raw")

    assert result == "file_result"
    assert captured_specs[0].input_file == csv_file


def test_filings_result_dataframe_and_index_access(tmp_path) -> None:
    import pyarrow.parquet as pq

    table = pa.Table.from_arrays(
        [
            pa.array(["0001181431-05-056000", "0000320193-23-000106"]),
            pa.array(["4", "10-K"]),
            pa.array(["2005-09-15", "2023-11-03"]),
            pa.array(
                [
                    "https://sec.gov/Archives/edgar/data/109694/000118143105056000/rrd.xml",
                    "https://sec.gov/Archives/edgar/data/320193/000032019323000106/aapl.htm",
                ]
            ),
            pa.array(["matched", "matched"]),
        ],
        names=["accession", "form", "filing_date", "target_url", "status"],
    )
    parquet_path = tmp_path / "targets.parquet"
    pq.write_table(table, parquet_path)

    res = FilingsResult(
        run_id="run-1",
        plan_id="plan-1",
        target_parquet_glob=str(parquet_path),
        run_state_sqlite_path=tmp_path / "state.sqlite",
        artifacts_root=tmp_path,
    )

    assert len(res) == 2
    df = res.to_df()
    assert len(df) == 2
    assert "accession" in df.columns

    cofilres = res.cofilers()
    assert len(cofilres) == 2
    assert set(cofilres["cik"]) == {"109694", "320193"}

    first_filing = res[0]
    assert first_filing.form in {"4", "10-K"}
    assert first_filing.run_id == "run-1"


def test_edgar_company_resolves_profile() -> None:
    edgar = Edgar()
    company = edgar.company("0000001750")
    assert company.cik.value == 1750
    assert company.name == "AAR CORP"
    assert "AIR" in company.tickers
