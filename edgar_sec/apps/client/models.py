"""Relational DataFrame results and lazy filing aggregate collection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

import duckdb
import pyarrow as pa

from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.filing_catalog.document_names import (
    is_primary_exhibit_filename,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.discovery.discovery import classify_linkbase
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths

if TYPE_CHECKING:
    import pandas as pd


from collections.abc import Sequence


def _is_exhibit_attachment(doc_type: str, filename: str) -> bool:
    dt = doc_type.upper()
    return dt.startswith("EX-") or is_primary_exhibit_filename(filename)


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

    def _all_filings(self) -> tuple[FilingAggregate, ...]:
        if self.items is not None:
            return self.items
        return tuple(self)

    def _catalog_table(self) -> pa.Table:
        filings = self._all_filings()
        accessions = [f.accession.value for f in filings]
        forms = [f.form for f in filings]
        filing_dates = [f.filing_date for f in filings]
        report_dates = [f.report_date or "" for f in filings]
        primary_docs = [
            f.primary_document_path
            or (f.primary_document_url.split("/")[-1] if f.primary_document_url else "")
            for f in filings
        ]
        primary_urls = [f.primary_document_url or "" for f in filings]
        return pa.Table.from_arrays(
            [
                pa.array(accessions, type=pa.string()),
                pa.array(forms, type=pa.string()),
                pa.array(filing_dates, type=pa.string()),
                pa.array(report_dates, type=pa.string()),
                pa.array(primary_docs, type=pa.string()),
                pa.array(primary_urls, type=pa.string()),
            ],
            names=[
                "accession",
                "form",
                "filing_date",
                "report_date",
                "primary_document",
                "primary_doc_url",
            ],
        )

    def _index_table(self) -> pa.Table:
        filings = self._all_filings()
        accs: list[str] = []
        seqs: list[int] = []
        dtypes: list[str] = []
        fnames: list[str] = []
        descs: list[str] = []
        sizes: list[int] = []
        urls: list[str] = []
        is_exs: list[bool] = []

        for f in filings:
            atts = f.get_attachments()
            for idx, a in enumerate(atts, 1):
                accs.append(f.accession.value)
                seq_val = idx
                try:
                    if a.attachment_id and a.attachment_id.isdigit():
                        seq_val = int(a.attachment_id)
                except Exception:
                    pass
                seqs.append(seq_val)
                dtypes.append(a.document_type)
                fnames.append(a.filename)
                descs.append(a.description or "")
                sizes.append(a.size or 0)
                urls.append(a.url)
                is_exs.append(_is_exhibit_attachment(a.document_type, a.filename))

        return pa.Table.from_arrays(
            [
                pa.array(accs, type=pa.string()),
                pa.array(seqs, type=pa.int32()),
                pa.array(dtypes, type=pa.string()),
                pa.array(fnames, type=pa.string()),
                pa.array(descs, type=pa.string()),
                pa.array(sizes, type=pa.int64()),
                pa.array(urls, type=pa.string()),
                pa.array(is_exs, type=pa.bool_()),
            ],
            names=[
                "accession",
                "sequence",
                "document_type",
                "filename",
                "description",
                "size",
                "url",
                "is_exhibit",
            ],
        )

    def _exhibits_table(self, types: Sequence[str] | str = ()) -> pa.Table:
        filings = self._all_filings()
        filter_types = (
            {types.upper()}
            if isinstance(types, str) and types
            else {t.upper() for t in types}
            if types
            else None
        )
        accs: list[str] = []
        forms: list[str] = []
        dtypes: list[str] = []
        descs: list[str] = []
        fnames: list[str] = []
        sizes: list[int] = []
        urls: list[str] = []

        for f in filings:
            for ex in f.exhibits:
                dt = ex.document_type
                if filter_types is not None:
                    matched = False
                    canon_dt = dt.upper()
                    for ft in filter_types:
                        canon_ft = f"EX-{ft}" if not ft.startswith("EX-") else ft
                        if (
                            canon_dt == canon_ft
                            or canon_dt == ft
                            or canon_dt.startswith(f"{canon_ft}.")
                        ):
                            matched = True
                            break
                    if not matched:
                        continue
                accs.append(f.accession.value)
                forms.append(f.form)
                dtypes.append(dt)
                descs.append(ex.description or "")
                fnames.append(ex.filename)
                sizes.append(ex.size or 0)
                urls.append(ex.url)

        return pa.Table.from_arrays(
            [
                pa.array(accs, type=pa.string()),
                pa.array(forms, type=pa.string()),
                pa.array(dtypes, type=pa.string()),
                pa.array(descs, type=pa.string()),
                pa.array(fnames, type=pa.string()),
                pa.array(sizes, type=pa.int64()),
                pa.array(urls, type=pa.string()),
            ],
            names=[
                "accession",
                "form",
                "document_type",
                "description",
                "filename",
                "size",
                "url",
            ],
        )

    def _linkbases_table(self) -> pa.Table:
        filings = self._all_filings()
        accs: list[str] = []
        forms: list[str] = []
        lb_types: list[str] = []
        dtypes: list[str] = []
        fnames: list[str] = []
        urls: list[str] = []

        for f in filings:
            for lb in f.linkbases:
                accs.append(f.accession.value)
                forms.append(f.form)
                lb_types.append(
                    classify_linkbase(
                        lb.document_type or "",
                        lb.filename or "",
                        lb.description or "",
                    ).value
                )
                dtypes.append(lb.document_type)
                fnames.append(lb.filename)
                urls.append(lb.url)

        return pa.Table.from_arrays(
            [
                pa.array(accs, type=pa.string()),
                pa.array(forms, type=pa.string()),
                pa.array(lb_types, type=pa.string()),
                pa.array(dtypes, type=pa.string()),
                pa.array(fnames, type=pa.string()),
                pa.array(urls, type=pa.string()),
            ],
            names=[
                "accession",
                "form",
                "linkbase_type",
                "document_type",
                "filename",
                "url",
            ],
        )

    def _payload_table(self) -> pa.Table:
        filings = self._all_filings()
        tids: list[str] = []
        accs: list[str] = []
        outcomes: list[str] = []
        attempts: list[int] = []
        durations: list[int] = []
        shas: list[str] = []
        sizes: list[int] = []
        paths: list[str] = []

        for idx, f in enumerate(filings, 1):
            tids.append(f"tgt_{idx:03d}")
            accs.append(f.accession.value)
            has_body = (
                f.primary_storage_path is not None and f.primary_storage_path.is_file()
            ) or f.fetcher is not None
            outcomes.append("acquired" if has_body else "planned")
            attempts.append(1)
            durations.append(0)
            shas.append(f.primary_sha256 or "")
            b_size = 0
            if f.primary_storage_path and f.primary_storage_path.is_file():
                try:
                    b_size = f.primary_storage_path.stat().st_size
                except OSError:
                    b_size = 0
            sizes.append(b_size)
            paths.append(str(f.primary_storage_path) if f.primary_storage_path else "")

        return pa.Table.from_arrays(
            [
                pa.array(tids, type=pa.string()),
                pa.array(accs, type=pa.string()),
                pa.array(outcomes, type=pa.string()),
                pa.array(attempts, type=pa.int32()),
                pa.array(durations, type=pa.int64()),
                pa.array(shas, type=pa.string()),
                pa.array(sizes, type=pa.int64()),
                pa.array(paths, type=pa.string()),
            ],
            names=[
                "target_id",
                "accession",
                "outcome",
                "attempt_count",
                "duration_ms",
                "body_sha256",
                "body_byte_size",
                "body_storage_path",
            ],
        )

    def _joined_table(self) -> pa.Table:
        filings = self._all_filings()
        accs: list[str] = []
        forms: list[str] = []
        filing_dates: list[str] = []
        primary_docs: list[str] = []
        outcomes: list[str] = []
        sizes: list[int | None] = []
        paths: list[str | None] = []
        urls: list[str] = []

        for f in filings:
            accs.append(f.accession.value)
            forms.append(f.form)
            filing_dates.append(f.filing_date)
            pdoc = f.primary_document_path or (
                f.primary_document_url.split("/")[-1] if f.primary_document_url else ""
            )
            primary_docs.append(pdoc)
            has_body = (
                f.primary_storage_path is not None and f.primary_storage_path.is_file()
            ) or f.fetcher is not None
            outcomes.append("acquired" if has_body else "planned")
            b_size = None
            if f.primary_storage_path and f.primary_storage_path.is_file():
                try:
                    b_size = f.primary_storage_path.stat().st_size
                except OSError:
                    pass
            sizes.append(b_size)
            paths.append(
                str(f.primary_storage_path) if f.primary_storage_path else None
            )
            urls.append(f.primary_document_url or "")

        return pa.Table.from_arrays(
            [
                pa.array(accs, type=pa.string()),
                pa.array(forms, type=pa.string()),
                pa.array(filing_dates, type=pa.string()),
                pa.array(primary_docs, type=pa.string()),
                pa.array(outcomes, type=pa.string()),
                pa.array(sizes, type=pa.int64()),
                pa.array(paths, type=pa.string()),
                pa.array(urls, type=pa.string()),
            ],
            names=[
                "accession",
                "form",
                "filing_date",
                "primary_document",
                "outcome",
                "body_byte_size",
                "body_storage_path",
                "target_url",
            ],
        )

    def sql(self, query: str, **params: Any) -> duckdb.DuckDBPyRelation:
        """Run arbitrary SQL across catalog, index, exhibits, linkbases, and payload."""
        con = connect()
        catalog_t = self._catalog_table()
        index_t = self._index_table()
        exhibits_t = self._exhibits_table()
        linkbases_t = self._linkbases_table()
        payload_t = self._payload_table()
        joined_t = self._joined_table()
        con.register("catalog", catalog_t)
        con.register("filings", catalog_t)
        con.register("index", index_t)
        con.register("attachments", index_t)
        con.register("exhibits", exhibits_t)
        con.register("linkbases", linkbases_t)
        con.register("payload", payload_t)
        con.register("staged", payload_t)
        con.register("joined", joined_t)
        return con.sql(query, params=params)

    def to_arrow(self) -> pa.Table:
        """Export core catalog filings table as a PyArrow Table."""
        return self._catalog_table()

    def to_df(self) -> pd.DataFrame:
        """Export core catalog filings table as a Pandas DataFrame."""
        return self.to_arrow().to_pandas()

    def attachments_df(self) -> pd.DataFrame:
        """Export submission envelope attachments table as a Pandas DataFrame."""
        return self._index_table().to_pandas()

    def exhibits(self, types: Sequence[str] | str = ()) -> pd.DataFrame:
        """Export exhibits table as a Pandas DataFrame."""
        return self._exhibits_table(types=types).to_pandas()

    def linkbases_df(self) -> pd.DataFrame:
        """Export verified XBRL linkbases table as a Pandas DataFrame."""
        return self._linkbases_table().to_pandas()

    def staged_df(self) -> pd.DataFrame:
        """Export execution payload and state table as a Pandas DataFrame."""
        return self._payload_table().to_pandas()

    def joined_df(self) -> pd.DataFrame:
        """Export consolidated joined table as a Pandas DataFrame."""
        return self._joined_table().to_pandas()

    def clean(self) -> int:
        """Delete transient execution files for this run."""
        from edgar_sec.apps.runner.cleanup import clear_transient

        return clear_transient(self.artifacts_root, run_id=self.run_id)

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
