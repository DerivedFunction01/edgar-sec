"""Local submissions snapshot reads for the fast path.

Builds the same ``FilingAggregate`` rows as the live submissions fetch from
the latest published submissions snapshot, so covered CIKs need no HTTP call.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.apps.client.fast_query.submissions import materialize_from_payload
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import Cik
from edgar_sec.foundation.runtime.paths import snapshots_root
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.traversal import walk_lineage
from edgar_sec.infra.storage.duckdb import connect, sql_literal

__all__ = ["materialize_from_snapshot"]

_METADATA_DATASET = "metadata"
_RELATION = "submissions"


def materialize_from_snapshot(
    ciks: Sequence[Any],
    forms: str | Sequence[str] | None,
    dates: str | None,
    limit: int | None,
    factories: dict[str, Any],
    doc_cache: DocumentCache,
    *,
    artifacts_root: Path | str,
) -> dict[str, list[FilingAggregate]]:
    """Return aggregates keyed by CIK for every CIK the snapshot covers.

    Absent CIKs are absent from the map (the caller's live-fetch signal), and
    any snapshot problem yields an empty map rather than an error.
    """
    wanted: dict[str, Any] = {}
    for cik in ciks or ():
        try:
            key = (cik if isinstance(cik, Cik) else Cik.from_raw(cik)).to_10digit()
        except Exception:
            continue
        wanted[key] = cik
    if not wanted:
        return {}
    try:
        return _read_snapshot_rows(
            wanted, forms, dates, limit, factories, doc_cache, artifacts_root
        )
    except Exception:
        return {}


def _read_snapshot_rows(
    wanted: dict[str, Any],
    forms: str | Sequence[str] | None,
    dates: str | None,
    limit: int | None,
    factories: dict[str, Any],
    doc_cache: DocumentCache,
    artifacts_root: Path | str,
) -> dict[str, list[FilingAggregate]]:
    root = snapshots_root(artifacts_root, _METADATA_DATASET)
    catalog = DAGCatalog(root, read_only=True)
    pointer = catalog.read_pointer("main")
    if pointer is None:
        return {}
    chain = walk_lineage(root, str(pointer["snapshot_id"]), read_only=True)
    covered: dict[str, list[FilingAggregate]] = {}
    remaining = dict(wanted)
    for node in reversed(chain.nodes):
        if not remaining:
            break
        if _RELATION not in node.relations:
            continue
        part_paths = catalog.resolve_relation(
            node.snapshot_id,
            _RELATION,
            relative_to=root / node.snapshot_id,
            verify_digests=False,
        )
        if not part_paths:
            continue
        payloads = _query_parts(part_paths, sorted(remaining))
        for cik_key, payload in payloads.items():
            covered[cik_key] = materialize_from_payload(
                remaining[cik_key],
                payload,
                forms,
                dates,
                limit,
                factories,
                doc_cache,
            )
            remaining.pop(cik_key, None)
    return covered


def _query_parts(
    part_paths: tuple[Path, ...], cik_keys: list[str]
) -> dict[str, dict[str, Any]]:
    cik_list = ", ".join(sql_literal(cik) for cik in cik_keys)
    paths = [str(path) for path in part_paths]
    with connect() as con:
        present = {
            str(row[0])
            for row in con.execute(
                f"SELECT DISTINCT cik FROM read_parquet(?) WHERE cik IN ({cik_list})",
                [paths],
            ).fetchall()
        }
        if not present:
            return {}
        filing_rows = con.execute(
            f"""
            SELECT cik,
                   f.accession_number, f.filing_date, f.report_date, f.form,
                   f.primary_document
            FROM (SELECT cik, unnest(filings) AS f FROM read_parquet(?))
            WHERE cik IN ({cik_list})
            """,
            [paths],
        ).fetchall()
    arrays: dict[str, dict[str, list[Any]]] = {
        cik: {
            "accessionNumber": [],
            "filingDate": [],
            "reportDate": [],
            "form": [],
            "primaryDocument": [],
        }
        for cik in present
    }
    for row in filing_rows:
        bucket = arrays[str(row[0])]
        bucket["accessionNumber"].append(row[1])
        bucket["filingDate"].append(row[2])
        bucket["reportDate"].append(row[3])
        bucket["form"].append(row[4])
        bucket["primaryDocument"].append(row[5])
    return {cik: {"filings": {"recent": bucket}} for cik, bucket in arrays.items()}
