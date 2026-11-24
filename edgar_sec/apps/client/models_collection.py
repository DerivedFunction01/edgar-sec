"""Collection protocol and lazy aggregate loading for FilingsResult."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.run_state.ephemeral import (
    read_ephemeral_targets,
)


_CIK_URL_RE = re.compile(r"/data/(\d+)/")


class CollectionMixin:
    """Collection protocol and lazy aggregate loading."""

    def _all_filings(self) -> tuple[FilingAggregate, ...]:
        if self.items is not None:
            return self.items
        return tuple(self)

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

    def __len__(self) -> int:
        if self.items is not None:
            return len(self.items)
        if self.snapshot_backed:
            rows = (
                self._snapshot_relation("SELECT count(*) AS n FROM selected_targets")
                .limit(1)
                .fetchall()
            )
            return int(rows[0][0])
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

        ephemeral_by_accession: dict[str, list[tuple[Any, ...]]] = {}
        if self.run_state_sqlite_path and self.run_state_sqlite_path.is_file():
            run_dir = self.run_state_sqlite_path.parent
            for record in read_ephemeral_targets(self.run_state_sqlite_path):
                if record["outcome"] != "acquired" or not record["body_relative_path"]:
                    continue
                body_path = run_dir / record["body_relative_path"]
                if not body_path.is_file():
                    continue
                storage_by_target[str(record["target_id"])] = body_path
                ephemeral_by_accession.setdefault(str(record["accession"]), []).append(
                    (
                        record["target_id"],
                        record["accession"],
                        "",
                        "",
                        record["target_url"],
                        record["target_role"],
                        record["document_type"] or record["target_type"],
                        "matched",
                        record["sequence"],
                        record["byte_size"],
                    )
                )

        from edgar_sec.engine.forms.render import render_filing

        def aggregate_for(group: list[tuple[Any, ...]]) -> FilingAggregate:
            basis = next((row for row in group if row[5] == "primary"), group[0])
            target_id, accession_str, form, filing_date, target_url = basis[:5]
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

            cik_match = _CIK_URL_RE.search(target_url) if target_url else None
            cik_inst = (
                Cik.from_raw(cik_match.group(1)) if cik_match else Cik.from_raw(1)
            )
            doc_path = target_url.split("/")[-1] if target_url else None
            effective_op = (self.family_operations or {}).get(
                str(form)
            ) or self.operation

            attachments: list[FilingAttachment] = []
            seen: set[tuple[str, str]] = set()
            for row in group:
                if row is basis or row[5] == "primary" or row[7] != "matched":
                    continue
                acquired_path = storage_by_target.get(str(row[0]))
                if acquired_path is None or not row[4]:
                    continue
                filename = row[4].split("/")[-1]
                key = (str(row[6] or ""), filename)
                if key in seen:
                    continue
                seen.add(key)
                attachments.append(
                    FilingAttachment(
                        attachment_id=str(row[8] or filename),
                        document_type=str(row[6] or ""),
                        filename=filename,
                        url=str(row[4]),
                        size=row[9] if isinstance(row[9], int) else None,
                        storage_path=acquired_path,
                    )
                )

            return FilingAggregate(
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
                attachments=tuple(attachments),
                renderer=lambda f, operation=None: render_filing(
                    f, operation=operation or effective_op
                ),
            )

        with connect() as con:
            schema_cols = {
                row[0]
                for row in con.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)",
                    [self.target_parquet_glob],
                ).fetchall()
            }
            rich = {
                "target_role",
                "target_type",
                "status",
                "sequence",
                "byte_size",
            } <= schema_cols
            if rich:
                cursor = con.execute(
                    "SELECT DISTINCT target_id, accession, form, filing_date, target_url, "
                    "target_role, target_type, status, sequence, byte_size "
                    "FROM read_parquet(?) ORDER BY accession, target_role, target_id",
                    [self.target_parquet_glob],
                )
            elif "target_id" in schema_cols:
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
            group: list[tuple[Any, ...]] = []
            group_accession: str | None = None
            while rows := cursor.fetchmany(resolve_read_batch_size()):
                for raw_row in rows:
                    row = (
                        tuple(raw_row)
                        if rich
                        else tuple(raw_row)
                        + ("primary", "primary", "matched", None, None)
                    )
                    if group_accession is not None and row[1] != group_accession:
                        group.extend(ephemeral_by_accession.get(group_accession, ()))
                        yield aggregate_for(group)
                        group = []
                    group_accession = row[1]
                    group.append(row)
            if group:
                group.extend(ephemeral_by_accession.get(group_accession or "", ()))
                yield aggregate_for(group)

    def __getitem__(self, index: int | slice) -> Any:
        if isinstance(index, slice):
            total = len(self)
            start, stop, step = index.indices(total)
            return [self[i] for i in range(start, stop, step)]
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
                item_query = f"SELECT * FROM ({self.query_sql}) LIMIT 1 OFFSET ?"
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
