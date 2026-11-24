"""Arrow table builders for FilingsResult."""

from __future__ import annotations

from collections.abc import Sequence

import pyarrow as pa

from edgar_sec.infra.storage.duckdb import arrow_table, connect

from edgar_sec.apps.client.tables import (
    build_catalog_table,
    build_exhibits_table,
    build_index_table,
    build_joined_table,
    build_linkbases_table,
    build_payload_table,
)


class TablesMixin:
    """Arrow table builders over the filing aggregates."""

    def _catalog_table(self) -> pa.Table:
        if self.query_backed and self.query_sql:
            with connect() as con:
                return arrow_table(con, self.query_sql, list(self.query_params))
        if self.items is None and not self.snapshot_backed and self.target_parquet_glob:
            with connect() as con:
                q = (
                    "SELECT DISTINCT accession, form, filing_date, "
                    "'' AS report_date, "
                    "regexp_extract(target_url, '[^/]+$', 0) AS primary_document, "
                    "target_url AS primary_doc_url "
                    "FROM read_parquet(?) ORDER BY accession"
                )
                return arrow_table(con, q, [self.target_parquet_glob])
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

    def _sections_table(self) -> pa.Table:
        from edgar_sec.apps.client.tables import build_sections_table

        return build_sections_table(self._all_filings())

    def _notes_table(self) -> pa.Table:
        from edgar_sec.apps.client.tables import build_notes_table

        return build_notes_table(self._all_filings())

    @property
    def sections(self) -> pa.Table:
        """Return Arrow table of resolved statutory sections for covered filings."""
        return self._sections_table()

    @property
    def notes(self) -> pa.Table:
        """Return Arrow table of financial statement footnotes for covered filings."""
        return self._notes_table()
