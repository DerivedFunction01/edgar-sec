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
    snapshot_id: str | None = None
    operation: str = "raw"
    family_operations: dict[str, str] | None = None
    items: tuple[FilingAggregate, ...] | None = None

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
        if self.items is not None:
            accessions = [f.accession.value for f in self.items]
            forms = [f.form for f in self.items]
            dates = [f.filing_date for f in self.items]
            urls = [f.primary_document_url or "" for f in self.items]
            statuses = [
                "acquired" if f.primary_storage_path else "planned" for f in self.items
            ]
            return pa.Table.from_arrays(
                [
                    pa.array(accessions, type=pa.string()),
                    pa.array(forms, type=pa.string()),
                    pa.array(dates, type=pa.string()),
                    pa.array(urls, type=pa.string()),
                    pa.array(statuses, type=pa.string()),
                ],
                names=[
                    "accession",
                    "form",
                    "filing_date",
                    "target_url",
                    "status",
                ],
            )
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
        return self.to_arrow().to_pandas()

    def cofilers(self) -> pd.DataFrame:
        """Return co-filers table linking accessions to all associated CIKs."""
        if self.items is not None:
            import pandas as pd

            acc_list: list[str] = []
            form_list: list[str] = []
            date_list: list[str] = []
            cik_list: list[str] = []
            for f in self.items:
                for c in f.ciks:
                    acc_list.append(f.accession.value)
                    form_list.append(f.form)
                    date_list.append(f.filing_date)
                    cik_list.append(str(c.value))
            return pd.DataFrame(
                {
                    "accession": acc_list,
                    "form": form_list,
                    "filing_date": date_list,
                    "cik": cik_list,
                }
            )
        query = (
            "SELECT accession, form, filing_date, "
            "regexp_extract(target_url, 'data/([0-9]+)/', 1) AS cik "
            "FROM read_parquet(?)"
        )
        with connect() as con:
            return con.execute(query, [self.target_parquet_glob]).df()

    def latest(self) -> FilingAggregate | None:
        """Return the latest filing by filing date, or None if empty."""
        filings = list(self)
        if not filings:
            return None
        return max(
            filings,
            key=lambda f: (f.filing_date, f.accession.value),
        )

    def first(self) -> FilingAggregate | None:
        """Return the first filing in the collection, or None if empty."""
        filings = list(self)
        return filings[0] if filings else None

    def filter(
        self,
        form: str | Sequence[str] | None = None,
        date: str | None = None,
        limit: int | None = None,
    ) -> FilingsResult:
        """Filter filings in-memory and return a new FilingsResult."""
        allowed_forms = {form} if isinstance(form, str) else set(form) if form else None
        filtered = [
            f
            for f in self
            if (allowed_forms is None or f.form in allowed_forms)
            and (date is None or f.filing_date.startswith(date))
        ]
        if limit is not None:
            filtered = filtered[: int(limit)]
        return FilingsResult(
            run_id=self.run_id,
            plan_id=self.plan_id,
            target_parquet_glob=self.target_parquet_glob,
            run_state_sqlite_path=self.run_state_sqlite_path,
            artifacts_root=self.artifacts_root,
            snapshot_id=self.snapshot_id,
            operation=self.operation,
            family_operations=self.family_operations,
            items=tuple(filtered),
        )

    def __len__(self) -> int:
        if self.items is not None:
            return len(self.items)
        with connect() as con:
            return con.execute(
                "SELECT count(DISTINCT accession) FROM read_parquet(?)",
                [self.target_parquet_glob],
            ).fetchone()[0]

    def __iter__(self) -> Iterator[FilingAggregate]:
        if self.items is not None:
            yield from self.items
            return
        storage_by_target: dict[str, Path] = {}
        if self.run_state_sqlite_path and self.run_state_sqlite_path.is_file():
            import sqlite3

            run_dir = self.run_state_sqlite_path.parent
            try:
                with sqlite3.connect(self.run_state_sqlite_path) as conn:
                    cols = {
                        r[1]
                        for r in conn.execute(
                            "PRAGMA table_info(target_state)"
                        ).fetchall()
                    }
                    if "selected_body_relative_path" in cols:
                        stmt = "SELECT target_id, selected_body_relative_path FROM target_state WHERE outcome = 'acquired'"
                    elif "source_body_relative_path" in cols:
                        stmt = "SELECT target_id, source_body_relative_path FROM target_state WHERE outcome = 'acquired'"
                    else:
                        stmt = "SELECT target_id, body_storage_path FROM target_state WHERE outcome = 'acquired'"
                    for tid, bpath in conn.execute(stmt):
                        if bpath:
                            full_path = run_dir / bpath
                            if full_path.is_file():
                                storage_by_target[str(tid)] = full_path
            except Exception:
                pass

        import re
        from edgar_sec.engine.forms.render import render_filing

        with connect() as con:
            schema_cols = {
                row[0]
                for row in con.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)",
                    [self.target_parquet_glob],
                ).fetchall()
            }
            if "target_id" in schema_cols:
                rows = con.execute(
                    "SELECT DISTINCT target_id, accession, form, filing_date, target_url "
                    "FROM read_parquet(?) "
                    "ORDER BY accession",
                    [self.target_parquet_glob],
                ).fetchall()
            else:
                raw_rows = con.execute(
                    "SELECT DISTINCT accession, form, filing_date, target_url "
                    "FROM read_parquet(?) "
                    "ORDER BY accession",
                    [self.target_parquet_glob],
                ).fetchall()
                rows = [(None, r[0], r[1], r[2], r[3]) for r in raw_rows]
        for target_id, accession_str, form, filing_date, target_url in rows:
            acc = AccessionNumber.from_any(accession_str)
            storage_path = storage_by_target.get(str(target_id))
            if storage_path is None:
                staging_dir = resolve_acquisition_paths(
                    self.artifacts_root
                ).run_staging_root(self.run_id)
                if staging_dir.is_dir():
                    matches = list(staging_dir.glob(f"*{acc.normalized}*"))
                    if matches:
                        storage_path = matches[0]

            cik_match = re.search(r"/data/(\d+)/", target_url) if target_url else None
            cik_inst = (
                Cik.from_raw(cik_match.group(1)) if cik_match else Cik.from_raw(1)
            )
            doc_path = target_url.split("/")[-1] if target_url else None
            effective_op = (self.family_operations or {}).get(
                str(form)
            ) or self.operation

            yield FilingAggregate(
                accession=acc,
                primary_cik=cik_inst,
                ciks=(cik_inst,),
                form=str(form),
                filing_date=str(filing_date or ""),
                primary_document_path=doc_path,
                primary_storage_path=storage_path,
                primary_document_url=target_url,
                run_id=self.run_id,
                plan_id=self.plan_id,
                renderer=lambda f, operation=None: render_filing(
                    f, operation=operation or effective_op
                ),
            )

    def __getitem__(self, index: int) -> FilingAggregate:
        if self.items is not None:
            return self.items[index]
        if index < 0:
            index = len(self) + index
        for current_idx, filing in enumerate(self):
            if current_idx == index:
                return filing
        raise IndexError(f"index {index} out of range for FilingsResult")


__all__ = ["FilingsResult"]
