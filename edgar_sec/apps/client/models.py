"""Relational DataFrame results and lazy filing aggregate collection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

import duckdb
import pyarrow as pa

from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.filing_catalog.filters import DateSelection
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths

from edgar_sec.apps.client.tables import (
    build_catalog_table,
    build_exhibits_table,
    build_index_table,
    build_joined_table,
    build_linkbases_table,
    build_payload_table,
)


@dataclass(frozen=True, slots=True)
class FilingsResult:
    """Relational DataFrame collection over planned and acquired filings."""

    run_id: str
    plan_id: str
    target_parquet_glob: str
    run_state_sqlite_path: Path
    artifacts_root: Path
    snapshot_id: str | None = None
    snapshot_backed: bool = False
    snapshot_forms: tuple[str, ...] = ()
    snapshot_ciks: tuple[str, ...] = ()
    snapshot_date_selection: DateSelection = ()
    snapshot_limit: int | None = None
    snapshot_filter_forms: tuple[str, ...] = ()
    snapshot_date_prefix: str | None = None
    snapshot_filter_limit: int | None = None
    snapshot_filter_empty: bool = False
    operation: str = "raw"
    family_operations: dict[str, str] | None = None
    items: tuple[FilingAggregate, ...] | None = None
    query_backed: bool = False
    query_sql: str | None = None
    query_params: tuple[Any, ...] = ()
    query_tables: dict[str, Any] | None = None
    query_factories: dict[str, Any] | None = None

    def _prepare_query_con(self, con: duckdb.DuckDBPyConnection) -> None:
        if self.query_tables:
            for tbl_name, tbl in self.query_tables.items():
                con.register(tbl_name, tbl)

    def _make_query_filing(self, row: tuple[Any, ...]) -> FilingAggregate:
        from edgar_sec.domain.identity import AccessionNumber, Cik

        acc_str, cik_val, form_val, f_date, r_date, p_doc, p_url = row
        acc = AccessionNumber.from_any(acc_str)
        cik_inst = Cik.from_raw(cik_val)
        factories = self.query_factories or {}
        return FilingAggregate(
            accession=acc,
            primary_cik=cik_inst,
            ciks=(cik_inst,),
            form=str(form_val),
            filing_date=str(f_date or ""),
            report_date=str(r_date) if r_date else None,
            primary_document_path=str(p_doc or ""),
            primary_document_url=str(p_url) if p_url else None,
            fetcher=factories.get("fetcher"),
            cache_clearer=factories.get("cache_clearer"),
            zip_exporter=factories.get("zip_exporter"),
            attachment_loader=factories.get("attachment_loader"),
            document_opener=factories.get("document_opener"),
            bundle_fetcher=factories.get("bundle_fetcher"),
            index_fetcher=factories.get("index_fetcher"),
            renderer=factories.get("renderer"),
        )

    def _all_filings(self) -> tuple[FilingAggregate, ...]:
        if self.items is not None:
            return self.items
        return tuple(self)

    def _catalog_table(self) -> pa.Table:
        if self.query_backed and self.query_sql:
            with connect() as con:
                return (
                    con.execute(self.query_sql, list(self.query_params))
                    .arrow()
                    .read_all()
                )
        if self.items is None and not self.snapshot_backed and self.target_parquet_glob:
            with connect() as con:
                q = (
                    "SELECT DISTINCT accession, form, filing_date, "
                    "'' AS report_date, "
                    "regexp_extract(target_url, '[^/]+$', 0) AS primary_document, "
                    "target_url AS primary_doc_url "
                    "FROM read_parquet(?) ORDER BY accession"
                )
                return con.execute(q, [self.target_parquet_glob]).arrow().read_all()
        return build_catalog_table(self._all_filings())

    def _index_table(self) -> pa.Table:
        return build_index_table(self._all_filings())

    def _exhibits_table(self, types: Sequence[str] | str = ()) -> pa.Table:
        return build_exhibits_table(self._all_filings(), types=types)

    def _linkbases_table(self) -> pa.Table:
        return build_linkbases_table(self._all_filings())

    def _payload_table(self) -> pa.Table:
        return build_payload_table(self._all_filings())

    def _joined_table(self) -> pa.Table:
        return build_joined_table(self._all_filings())

    def sql(self, query: str, **params: Any) -> duckdb.DuckDBPyRelation:
        """Run arbitrary SQL across catalog, index, exhibits, linkbases, and payload."""
        if self.snapshot_backed:
            return self._snapshot_relation(query, params)
        con = connect()
        if self.query_backed and self.query_sql:
            self._prepare_query_con(con)
            catalog_view_sql = f"CREATE TEMP VIEW catalog AS {self.query_sql}"
            con.execute(catalog_view_sql, list(self.query_params))
            con.execute("CREATE TEMP VIEW filings AS SELECT * FROM catalog")
            lower_q = query.lower()
            if any(t in lower_q for t in ("index", "attachments")):
                con.register("index", self._index_table())
                con.register("attachments", self._index_table())
            if "exhibits" in lower_q:
                con.register("exhibits", self._exhibits_table())
            if "linkbases" in lower_q:
                con.register("linkbases", self._linkbases_table())
            if any(t in lower_q for t in ("payload", "staged")):
                con.register("payload", self._payload_table())
                con.register("staged", self._payload_table())
            if "joined" in lower_q:
                con.register("joined", self._joined_table())
            return con.sql(query, params=params)
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

    def _snapshot_relation(
        self, query: str, params: dict[str, Any] | None = None
    ) -> duckdb.DuckDBPyRelation:
        from edgar_sec.apps.client.snapshots import register_snapshot_views

        con = connect()
        register_snapshot_views(
            con,
            self.artifacts_root,
            self.snapshot_id or "",
            forms=self.snapshot_forms,
            ciks=self.snapshot_ciks,
            dates=self.snapshot_date_selection,
            limit=self.snapshot_limit,
            filter_forms=self.snapshot_filter_forms,
            date_prefix=self.snapshot_date_prefix,
            filter_limit=self.snapshot_filter_limit,
            filter_empty=self.snapshot_filter_empty,
        )
        return con.sql(query, params=params or {})

    def to_arrow(self) -> pa.Table:
        """Export core catalog filings table as a PyArrow Table."""
        if self.snapshot_backed:
            return self._snapshot_relation("SELECT * FROM catalog").to_arrow_table()
        if self.query_backed and self.query_sql:
            with connect() as con:
                self._prepare_query_con(con)
                return (
                    con.execute(self.query_sql, list(self.query_params))
                    .arrow()
                    .read_all()
                )
        return self._catalog_table()

    def to_df(self) -> pd.DataFrame:
        """Export core catalog filings table as a Pandas DataFrame."""
        if self.snapshot_backed:
            return self._snapshot_relation("SELECT * FROM catalog").df()
        if self.query_backed and self.query_sql:
            with connect() as con:
                self._prepare_query_con(con)
                return con.execute(self.query_sql, list(self.query_params)).df()
        return self.to_arrow().to_pandas()

    def attachments_df(self) -> pd.DataFrame:
        """Export submission envelope attachments table as a Pandas DataFrame."""
        if self.snapshot_backed:
            return self._snapshot_relation("SELECT * FROM index").df()
        return self._index_table().to_pandas()

    def exhibits(self, types: Sequence[str] | str = ()) -> pd.DataFrame:
        """Export exhibits table as a Pandas DataFrame."""
        if self.snapshot_backed:
            filter_types = (
                (types.upper(),)
                if isinstance(types, str) and types
                else tuple(t.upper() for t in types)
                if types
                else ()
            )
            if not filter_types:
                return self._snapshot_relation("SELECT * FROM exhibits").df()
            clauses: list[str] = []
            values: dict[str, str] = {}
            for item in filter_types:
                canonical = item if item.startswith("EX-") else f"EX-{item}"
                slot = len(values)
                clauses.append(
                    f"(upper(document_type) = $p{slot} "
                    f"OR upper(document_type) = $p{slot + 1} "
                    f"OR upper(document_type) LIKE $p{slot + 2})"
                )
                values[f"p{slot}"] = canonical
                values[f"p{slot + 1}"] = item
                values[f"p{slot + 2}"] = f"{canonical}.%"
            return self._snapshot_relation(
                "SELECT * FROM exhibits WHERE " + " OR ".join(clauses),
                values,
            ).df()
        return self._exhibits_table(types=types).to_pandas()

    def linkbases_df(self) -> pd.DataFrame:
        """Export verified XBRL linkbases table as a Pandas DataFrame."""
        if self.snapshot_backed:
            return self._snapshot_relation("SELECT * FROM linkbases").df()
        return self._linkbases_table().to_pandas()

    def staged_df(self) -> pd.DataFrame:
        """Export execution payload and state table as a Pandas DataFrame."""
        if self.snapshot_backed:
            return self._snapshot_relation("SELECT * FROM staged").df()
        return self._payload_table().to_pandas()

    def joined_df(self) -> pd.DataFrame:
        """Export consolidated joined table as a Pandas DataFrame."""
        if self.snapshot_backed:
            return self._snapshot_relation("SELECT * FROM joined").df()
        return self._joined_table().to_pandas()

    def clean(self) -> int:
        """Delete transient execution files for this run."""
        from edgar_sec.apps.runner.cleanup import clear_transient

        return clear_transient(self.artifacts_root, run_id=self.run_id)

    def cofilers(self) -> pd.DataFrame:
        """Return co-filers table linking accessions to all associated CIKs."""
        if self.snapshot_backed:
            return self._snapshot_relation(
                "SELECT t.accession, t.form, t.filing_date, "
                "COALESCE(c.cik, t.cik) AS cik "
                "FROM selected_targets t LEFT JOIN accession_ciks c USING (accession) "
                "ORDER BY t.accession, c.cik"
            ).df()
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
        if self.snapshot_backed:
            from edgar_sec.apps.client.snapshots import snapshot_filing_at

            return snapshot_filing_at(self, latest=True)
        if self.query_backed and self.query_sql:
            with connect() as con:
                self._prepare_query_con(con)
                stmt = f"SELECT * FROM ({self.query_sql}) ORDER BY filing_date DESC, accession DESC LIMIT 1"
                row = con.execute(stmt, list(self.query_params)).fetchone()
                return self._make_query_filing(row) if row is not None else None
        return max(
            self,
            key=lambda f: (f.filing_date, f.accession.value),
            default=None,
        )

    def first(self) -> FilingAggregate | None:
        """Return the first filing in the collection, or None if empty."""
        if self.snapshot_backed:
            from edgar_sec.apps.client.snapshots import snapshot_filing_at

            return snapshot_filing_at(self)
        if self.query_backed and self.query_sql:
            with connect() as con:
                self._prepare_query_con(con)
                stmt = f"SELECT * FROM ({self.query_sql}) LIMIT 1"
                row = con.execute(stmt, list(self.query_params)).fetchone()
                return self._make_query_filing(row) if row is not None else None
        return next(iter(self), None)

    def filter(
        self,
        form: str | Sequence[str] | None = None,
        date: str | None = None,
        limit: int | None = None,
    ) -> FilingsResult:
        """Filter filings and return a new FilingsResult."""
        allowed_forms = {form} if isinstance(form, str) else set(form) if form else None
        if self.items is None and self.snapshot_backed:
            existing_forms = set(self.snapshot_filter_forms)
            if allowed_forms is not None:
                existing_forms = (
                    existing_forms & allowed_forms if existing_forms else allowed_forms
                )
            empty = self.snapshot_filter_empty or (
                allowed_forms is not None and not existing_forms
            )
            prefix = self.snapshot_date_prefix
            if date is not None:
                if prefix is not None and not (
                    prefix.startswith(date) or date.startswith(prefix)
                ):
                    empty = True
                else:
                    prefix = (
                        max((prefix, date), key=len) if prefix is not None else date
                    )
            new_limit = self.snapshot_filter_limit
            if limit is not None:
                new_limit = (
                    int(limit) if new_limit is None else min(new_limit, int(limit))
                )
            return replace(
                self,
                snapshot_filter_forms=tuple(sorted(existing_forms)),
                snapshot_date_prefix=prefix,
                snapshot_filter_limit=new_limit,
                snapshot_filter_empty=empty,
            )
        if self.query_backed and self.query_sql:
            clauses: list[str] = []
            params: list[Any] = list(self.query_params)
            if allowed_forms:
                forms_list = sorted(allowed_forms)
                placeholders = ", ".join(["?"] * len(forms_list))
                clauses.append(f"form IN ({placeholders})")
                params.extend(forms_list)
            if date is not None:
                clauses.append("filing_date LIKE ?")
                params.append(f"{date}%")
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            limit_sql = f"LIMIT {int(limit)}" if limit is not None else ""
            new_query = f"SELECT * FROM ({self.query_sql}) {where_sql} {limit_sql}"
            return replace(
                self,
                query_sql=new_query,
                query_params=tuple(params),
            )
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
        if self.snapshot_backed:
            return int(
                self._snapshot_relation(
                    "SELECT count(*) AS n FROM selected_targets"
                ).fetchone()[0]
            )
        if self.query_backed and self.query_sql:
            with connect() as con:
                self._prepare_query_con(con)
                count_query = f"SELECT count(*) FROM ({self.query_sql})"
                res = con.execute(count_query, list(self.query_params)).fetchone()
                return int(res[0]) if res else 0
        with connect() as con:
            return con.execute(
                "SELECT count(DISTINCT accession) FROM read_parquet(?)",
                [self.target_parquet_glob],
            ).fetchone()[0]

    def __iter__(self) -> Iterator[FilingAggregate]:
        if self.items is not None:
            yield from self.items
            return
        if self.snapshot_backed:
            from edgar_sec.apps.client.snapshots import iter_snapshot_filings

            yield from iter_snapshot_filings(self)
            return
        if self.query_backed and self.query_sql:
            with connect() as con:
                self._prepare_query_con(con)
                cursor = con.execute(self.query_sql, list(self.query_params))
                while rows := cursor.fetchmany(resolve_read_batch_size()):
                    for row in rows:
                        yield self._make_query_filing(row)
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
                cursor = con.execute(
                    "SELECT DISTINCT target_id, accession, form, filing_date, target_url "
                    "FROM read_parquet(?) ORDER BY accession",
                    [self.target_parquet_glob],
                )
            else:
                cursor = con.execute(
                    "SELECT DISTINCT NULL AS target_id, accession, form, filing_date, target_url "
                    "FROM read_parquet(?) ORDER BY accession",
                    [self.target_parquet_glob],
                )
            while rows := cursor.fetchmany(resolve_read_batch_size()):
                for target_id, accession_str, form, filing_date, target_url in rows:
                    acc = AccessionNumber.from_any(accession_str)
                    storage_path = storage_by_target.get(str(target_id))
                    if storage_path is None:
                        staging_dir = resolve_acquisition_paths(
                            artifacts_root=self.artifacts_root
                        ).run_staging_root(self.run_id)
                        if staging_dir.is_dir():
                            matches = list(staging_dir.glob(f"*{acc.normalized}*"))
                            if matches:
                                storage_path = matches[0]

                    cik_match = (
                        re.search(r"/data/(\d+)/", target_url) if target_url else None
                    )
                    cik_inst = (
                        Cik.from_raw(cik_match.group(1))
                        if cik_match
                        else Cik.from_raw(1)
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
        if self.snapshot_backed:
            from edgar_sec.apps.client.snapshots import snapshot_filing_at

            resolved_index = index if index >= 0 else len(self) + index
            if resolved_index < 0:
                raise IndexError(f"index {index} out of range for FilingsResult")
            filing = snapshot_filing_at(self, offset=resolved_index)
            if filing is None:
                raise IndexError(f"index {index} out of range for FilingsResult")
            return filing
        if self.query_backed and self.query_sql:
            resolved_index = index if index >= 0 else len(self) + index
            if resolved_index < 0:
                raise IndexError(f"index {index} out of range for FilingsResult")
            with connect() as con:
                self._prepare_query_con(con)
                item_query = f"{self.query_sql} LIMIT 1 OFFSET ?"
                row = con.execute(
                    item_query,
                    [*self.query_params, int(resolved_index)],
                ).fetchone()
                if row is None:
                    raise IndexError(f"index {index} out of range for FilingsResult")
                return self._make_query_filing(row)
        if index < 0:
            index = len(self) + index
        for current_idx, filing in enumerate(self):
            if current_idx == index:
                return filing
        raise IndexError(f"index {index} out of range for FilingsResult")


__all__ = ["FilingsResult"]
