"""Relational and DataFrame exports for FilingsResult."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from edgar_sec.infra.storage.duckdb import arrow_table, connect, relation_table

if TYPE_CHECKING:
    import pandas as pd

    from edgar_sec.infra.storage.duckdb import Relation


class ExportsMixin:
    """Relational queries and DataFrame exports."""

    def sql(self, query: str, **params: Any) -> Relation:
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
            if "sections" in lower_q:
                con.register("sections", self._sections_table())
            if "notes" in lower_q:
                con.register("notes", self._notes_table())
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
        lower_q = query.lower()
        if "sections" in lower_q:
            con.register("sections", self._sections_table())
        if "notes" in lower_q:
            con.register("notes", self._notes_table())
        return con.sql(query, params=params)

    def _snapshot_relation(
        self, query: str, params: dict[str, Any] | None = None
    ) -> Relation:
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
            return relation_table(self._snapshot_relation("SELECT * FROM catalog"))
        if self.query_backed and self.query_sql:
            with connect() as con:
                self._prepare_query_con(con)
                return arrow_table(con, self.query_sql, list(self.query_params))
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

    def sections_df(self) -> pd.DataFrame:
        """Export resolved statutory sections table as a Pandas DataFrame."""
        if self.snapshot_backed:
            return self._snapshot_relation("SELECT * FROM sections").df()
        return self._sections_table().to_pandas()

    def notes_df(self) -> pd.DataFrame:
        """Export financial statement footnotes table as a Pandas DataFrame."""
        if self.snapshot_backed:
            return self._snapshot_relation("SELECT * FROM notes").df()
        return self._notes_table().to_pandas()

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
