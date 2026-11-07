"""Tests for local submissions snapshot reads in the fast path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.apps.client.fast_query.submissions import collect_submissions_fallback
from edgar_sec.apps.client.fast_query.submissions_local import (
    materialize_from_snapshot,
)
from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.engine.submissions.builder import (
    build_submission_table,
    normalize_submissions,
)
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import snapshots_root
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest, PartDescriptor

FORD = "0000037996"
OTHER = "0000999999"
SNAPSHOT_ID = "snap-local-1"


def _payload(accession: str, form: str = "10-K") -> dict[str, Any]:
    return {
        "name": "FORD MOTOR CO",
        "filings": {
            "recent": {
                "accessionNumber": [accession],
                "filingDate": ["2026-01-02"],
                "reportDate": ["2025-12-31"],
                "form": [form],
                "primaryDocument": ["ford.htm"],
            },
            "files": [],
        },
    }


def _publish_snapshot(
    tmp_path: Path,
    rows: list[dict[str, Any]],
    *,
    created_at: str | None = None,
) -> None:
    from datetime import UTC, datetime

    root = snapshots_root(tmp_path, "metadata")
    snapshot_dir = root / SNAPSHOT_ID
    parts_dir = snapshot_dir / "parts"
    parts_dir.mkdir(parents=True)
    part_path = parts_dir / "part-000.parquet"
    pq.write_table(build_submission_table(rows), part_path)
    manifest = DAGNodeManifest(
        snapshot_id=SNAPSHOT_ID,
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id=SNAPSHOT_ID,
        lineage_depth=0,
        created_at=created_at or datetime.now(UTC).isoformat(timespec="seconds"),
        relations={
            "submissions": (
                PartDescriptor(
                    path="parts/part-000.parquet",
                    sha256=file_sha256(part_path),
                    row_count=len(rows),
                    byte_size=part_path.stat().st_size,
                ),
            )
        },
        logical_fingerprint="",
        schema_versions={"submissions": "1.0.0"},
    )
    DAGCatalog(root).publish_node(manifest, branch_name="main")


def _row(cik: str, payload: dict[str, Any]) -> dict[str, Any]:
    return normalize_submissions(
        payload,
        cik_padded=cik,
        input_name="test",
        snapshot_id=SNAPSHOT_ID,
        fetched_at="2026-01-01T00:00:00Z",
        source_url=submissions_url(cik),
        byte_count=1,
        historical_payloads=[],
        historical_errors=[],
        response_sha256="a" * 64,
        input_fingerprint="fp",
        chunk_id=0,
    )


class _ExplodingClient:
    """Transport fake that fails the test on any HTTP attempt."""

    def get_bytes(self, url: str) -> bytes:
        raise AssertionError(f"unexpected HTTP fetch: {url}")


class _LiveClient:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def get_bytes(self, url: str) -> bytes:
        self.calls.append(url)
        return json.dumps(self.payloads[url]).encode("utf-8")


def test_covered_cik_is_served_locally_without_http(tmp_path: Path) -> None:
    _publish_snapshot(tmp_path, [_row(FORD, _payload(f"{FORD}-26-000001"))])
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")

    items = collect_submissions_fallback(
        [FORD],
        None,
        None,
        None,
        {},
        _ExplodingClient(),
        cache,
        artifacts_root=tmp_path,
    )

    assert len(items) == 1
    assert items[0].accession.raw == f"{FORD}-26-000001"
    assert items[0].form == "10-K"
    assert items[0].primary_document_path == "ford.htm"


def test_uncovered_cik_falls_back_to_live_fetch(tmp_path: Path) -> None:
    _publish_snapshot(tmp_path, [_row(FORD, _payload(f"{FORD}-26-000001"))])
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    live = _LiveClient(
        {submissions_url(OTHER): _payload(f"{OTHER}-26-000777", form="8-K")}
    )

    items = collect_submissions_fallback(
        [FORD, OTHER],
        None,
        None,
        None,
        {},
        live,
        cache,
        artifacts_root=tmp_path,
    )

    assert {item.accession.raw for item in items} == {
        f"{FORD}-26-000001",
        f"{OTHER}-26-000777",
    }
    assert live.calls == [submissions_url(OTHER)]


def test_a_stale_snapshot_is_not_served_locally(tmp_path: Path) -> None:
    """Freshness is the submissions policy's question, not the caller's."""
    _publish_snapshot(
        tmp_path,
        [_row(FORD, _payload(f"{FORD}-26-000001"))],
        created_at="2020-01-01T00:00:00+00:00",
    )
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    live = _LiveClient({submissions_url(FORD): _payload(f"{FORD}-26-000002")})

    items = collect_submissions_fallback(
        [FORD],
        None,
        None,
        None,
        {},
        live,
        cache,
        artifacts_root=tmp_path,
    )

    assert [item.accession.raw for item in items] == [f"{FORD}-26-000002"]
    assert live.calls == [submissions_url(FORD)]


def test_no_snapshot_published_yields_no_local_coverage(tmp_path: Path) -> None:
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")

    covered = materialize_from_snapshot(
        [FORD], None, None, None, {}, cache, artifacts_root=tmp_path
    )

    assert covered == {}


def _publish_multi_part_snapshot(
    tmp_path: Path,
    parts: list[list[tuple[str, dict[str, Any]]]],
    *,
    row_count_overrides: dict[int, int] | None = None,
) -> Path:
    """Publish one snapshot whose submissions rows span several parts.

    Returns the snapshot directory so a test can damage a part on disk.
    """
    from datetime import UTC, datetime

    root = snapshots_root(tmp_path, "metadata")
    snapshot_dir = root / SNAPSHOT_ID
    parts_dir = snapshot_dir / "parts"
    parts_dir.mkdir(parents=True)
    descriptors: list[PartDescriptor] = []
    all_ciks: list[str] = []
    for i, part in enumerate(parts):
        part_path = parts_dir / f"part-{i:03d}.parquet"
        rows = [_row(cik, payload) for cik, payload in part]
        pq.write_table(build_submission_table(rows), part_path)
        row_count = len(rows)
        if row_count_overrides and i in row_count_overrides:
            row_count = row_count_overrides[i]
        descriptors.append(
            PartDescriptor(
                path=f"parts/part-{i:03d}.parquet",
                sha256=file_sha256(part_path),
                row_count=row_count,
                byte_size=part_path.stat().st_size,
            )
        )
        all_ciks.extend(cik for cik, _ in part)
    index_path = snapshot_dir / "ciks.parquet"
    distinct_ciks = sorted(set(all_ciks))
    pq.write_table(pa.table({"cik": distinct_ciks}), index_path)
    manifest = DAGNodeManifest(
        snapshot_id=SNAPSHOT_ID,
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id=SNAPSHOT_ID,
        lineage_depth=0,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        relations={
            "submissions": tuple(descriptors),
            "cik_index": (
                PartDescriptor(
                    path="ciks.parquet",
                    sha256=file_sha256(index_path),
                    row_count=len(distinct_ciks),
                    byte_size=index_path.stat().st_size,
                ),
            ),
        },
        logical_fingerprint="",
        schema_versions={"submissions": "1.0.0"},
    )
    DAGCatalog(root).publish_node(manifest, branch_name="main")
    return snapshot_dir


def test_multi_part_lookup_reads_only_the_target_part(tmp_path: Path) -> None:
    """Non-target parts are unreadable garbage; the lookup must not open them."""
    snapshot_dir = _publish_multi_part_snapshot(
        tmp_path,
        [
            [("0000000123", _payload("0000000123-26-000001"))],
            [(FORD, _payload(f"{FORD}-26-000001"))],
            [(OTHER, _payload(f"{OTHER}-26-000001"))],
        ],
    )
    for name in ("part-000.parquet", "part-002.parquet"):
        (snapshot_dir / "parts" / name).write_bytes(b"not parquet")
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")

    items = collect_submissions_fallback(
        [FORD],
        None,
        None,
        None,
        {},
        _ExplodingClient(),
        cache,
        artifacts_root=tmp_path,
    )

    assert len(items) == 1
    assert items[0].accession.raw == f"{FORD}-26-000001"


def test_index_row_count_drift_falls_back_to_full_scan(tmp_path: Path) -> None:
    """Descriptor counts that fail to partition the index refuse targeting."""
    _publish_multi_part_snapshot(
        tmp_path,
        [
            [("0000000123", _payload("0000000123-26-000001"))],
            [(FORD, _payload(f"{FORD}-26-000001"))],
        ],
        row_count_overrides={0: 5},
    )
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")

    covered = materialize_from_snapshot(
        [FORD], None, None, None, {}, cache, artifacts_root=tmp_path
    )

    assert set(covered) == {FORD}
    assert covered[FORD][0].accession.raw == f"{FORD}-26-000001"


def test_cik_absent_from_index_is_not_covered_locally(tmp_path: Path) -> None:
    _publish_multi_part_snapshot(
        tmp_path,
        [[(FORD, _payload(f"{FORD}-26-000001"))]],
    )
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    live = _LiveClient(
        {submissions_url(OTHER): _payload(f"{OTHER}-26-000777", form="8-K")}
    )

    items = collect_submissions_fallback(
        [OTHER],
        None,
        None,
        None,
        {},
        live,
        cache,
        artifacts_root=tmp_path,
    )

    assert [item.accession.raw for item in items] == [f"{OTHER}-26-000777"]
    assert live.calls == [submissions_url(OTHER)]
