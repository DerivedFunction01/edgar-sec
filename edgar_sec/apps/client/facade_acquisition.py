"""Live acquisition surface of the Edgar facade: pipeline, fetch, and file fetch."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

from edgar_sec.apps.client.fast_query.query import query_catalog_fast
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.runner.config import DateFilterInput, FilingQuery, PipelineConfig
from edgar_sec.apps.runner.coordinator import PipelineRunner


class AcquisitionMixin:
    """Acquisition methods composed into the Edgar facade."""

    def pipeline(self, config: PipelineConfig | FilingQuery) -> FilingsResult:
        """Execute end-to-end acquisition via the high-throughput pipeline runner."""
        if not isinstance(config, PipelineConfig):
            config = PipelineConfig(
                tickers=config.tickers,
                ciks=config.ciks,
                accessions=config.accessions,
                input_file=config.input_file,
                forms=config.forms,
                dates=config.dates,
                roles=config.roles,
                suffixes=config.suffixes,
                limit=config.limit,
                operations=config.operations,
                artifacts_root=self.artifacts_root,
                workers=self.workers,
                sec_client=self.sec_client,
            )
        runner = PipelineRunner(config)
        return runner.run(config)

    def fetch(
        self,
        query: FilingQuery | PipelineConfig | None = None,
        *,
        forms: Sequence[str] | str = (),
        ciks: Sequence[str | int] | str | int = (),
        tickers: Sequence[str] | str = (),
        accessions: Sequence[str] | str = (),
        dates: DateFilterInput = None,
        suffixes: Sequence[str] | str = (),
        roles: Sequence[str] | str = ("primary",),
        limit: int | None = None,
        operation: str | None = None,
        operations: Sequence[str] | str = (),
        family_operations: dict[str, str] | None = None,
        mode: Literal["fast", "pipeline", "snapshot"] = "fast",
        snapshot: str = "main",
        workers: int | None = None,
    ) -> FilingsResult:
        """Execute acquisition and return a relational FilingsResult."""
        if mode == "snapshot":
            from edgar_sec.apps.client.snapshots import (
                query_filings_from_snapshot,
            )

            form_tuple = (
                query.forms
                if query is not None
                else (
                    (forms,) if isinstance(forms, str) else tuple(str(f) for f in forms)
                )
            )
            cik_tuple = (
                query.ciks
                if query is not None
                else (
                    (str(ciks),)
                    if isinstance(ciks, (str, int))
                    else tuple(str(c) for c in ciks)
                )
            )
            date_filter = query.dates if query is not None else dates
            limit_val = query.limit if query is not None else limit
            return query_filings_from_snapshot(
                self.artifacts_root,
                snapshot_id_or_tag=snapshot,
                forms=form_tuple,
                ciks=cik_tuple,
                dates=date_filter,
                limit=limit_val,
            )

        if query is not None:
            if mode == "pipeline" or query.roles != ("primary",) or query.input_file:
                return self.pipeline(query)
            form_tuple = query.forms
            cik_tuple = query.ciks
            date_str = query.resolved_date_string()
            limit_val = query.limit
            op_val = query.operations[0] if query.operations else "raw"
            return query_catalog_fast(
                ciks=cik_tuple,
                forms=form_tuple,
                dates=date_str,
                limit=limit_val,
                operation=op_val,
                artifacts_root=self.artifacts_root,
                cache=self.cache,
                http_client_factory=(
                    (lambda: self.sec_client) if self.sec_client else None
                ),
            )

        form_tuple = (
            (forms,) if isinstance(forms, str) else tuple(str(f) for f in forms)
        )
        cik_tuple = (
            (str(ciks),)
            if isinstance(ciks, (str, int))
            else tuple(str(c) for c in ciks)
        )
        ticker_tuple = (
            (tickers,) if isinstance(tickers, str) else tuple(str(t) for t in tickers)
        )
        acc_tuple = (
            (accessions,)
            if isinstance(accessions, str)
            else tuple(str(a) for a in accessions)
        )
        role_tuple = (
            (roles,) if isinstance(roles, str) else tuple(str(r) for r in roles)
        )
        suffix_tuple = (
            (suffixes,)
            if isinstance(suffixes, str)
            else tuple(str(s) for s in suffixes)
        )
        op_list = (
            tuple(operations)
            if operations
            else ((operation,) if operation is not None else ())
        )

        q = FilingQuery(
            tickers=ticker_tuple,
            ciks=cik_tuple,
            accessions=acc_tuple,
            forms=form_tuple,
            dates=dates,
            roles=role_tuple,
            suffixes=suffix_tuple,
            limit=limit,
            operations=op_list,
        )
        if mode == "fast" and role_tuple == ("primary",) and not acc_tuple:
            resolved_ciks = list(cik_tuple)
            for t in ticker_tuple:
                from edgar_sec.apps.client.reference.resolver import (
                    resolve_entity_profile,
                )

                prof = resolve_entity_profile(t, self.artifacts_root)
                if prof and prof.cik:
                    resolved_ciks.append(str(prof.cik.value))
            return query_catalog_fast(
                ciks=tuple(resolved_ciks),
                forms=form_tuple,
                dates=q.resolved_date_string(),
                limit=limit,
                operation=op_list[0] if op_list else None,
                family_operations=family_operations,
                artifacts_root=self.artifacts_root,
                cache=self.cache,
                http_client_factory=(
                    (lambda: self.sec_client) if self.sec_client else None
                ),
            )

        config = PipelineConfig(
            tickers=ticker_tuple,
            ciks=cik_tuple,
            accessions=acc_tuple,
            forms=form_tuple,
            dates=dates,
            roles=role_tuple,
            suffixes=suffix_tuple,
            limit=limit,
            operations=op_list,
            workers=workers if workers is not None else self.workers,
            sec_client=self.sec_client,
            artifacts_root=self.artifacts_root,
        )
        return self.pipeline(config)

    def fetch_from_file(
        self,
        file_path: Path | str,
        *,
        forms: Sequence[str] | str = (),
        roles: Sequence[str] | str = ("primary",),
        operation: str = "raw",
        operations: Sequence[str] | str = (),
        workers: int | None = None,
    ) -> FilingsResult:
        """Execute end-to-end acquisition against an arbitrary DuckDB-readable file."""
        op_list = tuple(operations) if operations else (operation,)
        config = PipelineConfig(
            input_file=Path(file_path),
            forms=(forms,) if isinstance(forms, str) else tuple(str(f) for f in forms),
            roles=(roles,) if isinstance(roles, str) else tuple(str(r) for r in roles),
            operations=op_list,
            workers=workers if workers is not None else self.workers,
            sec_client=self.sec_client,
            artifacts_root=self.artifacts_root,
        )
        return self.pipeline(config)
