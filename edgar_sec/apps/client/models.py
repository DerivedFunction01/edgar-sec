"""Relational DataFrame results and lazy filing aggregate collection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.models_collection import CollectionMixin
from edgar_sec.apps.client.models_exports import ExportsMixin
from edgar_sec.apps.client.models_query import QueryMixin
from edgar_sec.apps.client.models_tables import TablesMixin
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.filing_catalog.filters import DateSelection

__all__ = ["FilingsResult"]


@dataclass(frozen=True, slots=True)
class FilingsResult(QueryMixin, TablesMixin, ExportsMixin, CollectionMixin):
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

    def clean(self) -> int:
        """Delete transient execution files for this run."""
        from edgar_sec.apps.runner.cleanup import clear_transient

        return clear_transient(self.artifacts_root, run_id=self.run_id)

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
