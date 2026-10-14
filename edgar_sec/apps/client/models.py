"""Relational DataFrame results and lazy filing aggregate collection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

import duckdb
import pyarrow as pa

from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True, slots=True)
class FilingsResult:
    """Relational DataFrame collection over planned and acquired filings."""

    run_id: str
    plan_id: str
    target_parquet_glob: str
    run_state_sqlite_path: Path
    artifacts_root: Path

    def sql(self, query: str, **params: Any) -> duckdb.DuckDBPyRelation:
        """Run arbitrary SQL across filings, cofilers, and targets."""
        con = connect()
        con.execute(
            "CREATE TEMP VIEW filings AS "
            "SELECT DISTINCT accession, form, filing_date, target_url, status "
            "FROM read_parquet(?)",
            [self.target_parquet_glob],
        )
        return con.sql(query, params=params)

    def to_arrow(self) -> pa.Table:
        """Export core filings table as a PyArrow Table."""
        with connect() as con:
            return (
                con.execute(
                    "SELECT accession, form, filing_date, target_url, status "
                    "FROM read_parquet(?) "
                    "ORDER BY accession",
                    [self.target_parquet_glob],
                )
                .arrow()
                .read_all()
            )

    def to_df(self) -> pd.DataFrame:
        """Export core filings table as a Pandas DataFrame."""
        with connect() as con:
            return con.execute(
                "SELECT accession, form, filing_date, target_url, status "
                "FROM read_parquet(?) "
                "ORDER BY accession",
                [self.target_parquet_glob],
            ).df()

    def cofilers(self) -> pd.DataFrame:
        """Return co-filers table linking accessions to all associated CIKs."""
        query = (
            "SELECT accession, form, filing_date, "
            "regexp_extract(target_url, 'data/([0-9]+)/', 1) AS cik "
            "FROM read_parquet(?)"
        )
        with connect() as con:
            return con.execute(query, [self.target_parquet_glob]).df()

    def __len__(self) -> int:
        with connect() as con:
            return con.execute(
                "SELECT count(DISTINCT accession) FROM read_parquet(?)",
                [self.target_parquet_glob],
            ).fetchone()[0]

    def __iter__(self) -> Iterator[FilingAggregate]:
        with connect() as con:
            rows = con.execute(
                "SELECT DISTINCT accession, form, filing_date, target_url "
                "FROM read_parquet(?) "
                "ORDER BY accession",
                [self.target_parquet_glob],
            ).fetchall()
        for accession_str, form, filing_date, target_url in rows:
            acc = AccessionNumber.from_any(accession_str)
            storage_path = None
            staging_dir = resolve_acquisition_paths(
                self.artifacts_root
            ).run_staging_root(self.run_id)
            if staging_dir.is_dir():
                matches = list(staging_dir.glob(f"*{acc.normalized}*"))
                if matches:
                    storage_path = matches[0]

            yield FilingAggregate(
                accession=acc,
                primary_cik=Cik.from_raw(1),
                ciks=(Cik.from_raw(1),),
                form=form,
                filing_date=filing_date or "",
                primary_storage_path=storage_path,
                run_id=self.run_id,
                plan_id=self.plan_id,
            )

    def __getitem__(self, index: int) -> FilingAggregate:
        if index < 0:
            index = len(self) + index
        for current_idx, filing in enumerate(self):
            if current_idx == index:
                return filing
        raise IndexError(f"index {index} out of range for FilingsResult")


__all__ = ["FilingsResult"]
