"""Query-backed support for FilingsResult."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from edgar_sec.domain.document.aggregate import FilingAggregate

if TYPE_CHECKING:
    from edgar_sec.infra.storage.duckdb import Connection


class QueryMixin:
    """Query-backed support: table registration and row mapping."""

    def _prepare_query_con(self, con: Connection) -> None:
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
