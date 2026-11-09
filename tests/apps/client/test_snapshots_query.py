"""Tests for offline snapshot retrieval and query engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.snapshots import (
    attachment_role_sql,
    classify_linkbase_sql,
    is_exhibit_sql,
    query_filings_from_snapshot,
    register_form_alias_map,
)
from edgar_sec.apps.client.tables import (
    build_exhibits_table,
    build_index_table,
    build_linkbases_table,
    build_payload_table,
)
from edgar_sec.domain.document.aggregate import is_exhibit_attachment
from edgar_sec.domain.document.canonical import attachment_role
from edgar_sec.engine.xbrl.discovery.discovery import classify_linkbase
from edgar_sec.domain.filing_catalog.filters import DateRange
from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.infra.storage.duckdb import connect, sql_identifier
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.writer import (
    publish_acquisition_run,
)
from tests.pipelines.document_acquisition.snapshot.test_writer import _setup_run


def test_query_filings_from_snapshot(tmp_path: Path, monkeypatch) -> None:
    """Verify querying filings directly from published snapshot."""
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")

    payload_loads = []

    def load_payload(*args):
        payload_loads.append(args[-1])
        return b"<html>Sample filing content</html>"

    monkeypatch.setattr(
        "edgar_sec.apps.client.snapshots._load_snapshot_payload", load_payload
    )
    res = query_filings_from_snapshot(tmp_path, snapshot_id_or_tag="main")
    assert len(res) == 1
    filing = res[0]
    assert filing.form == "10-K"
    assert res.first().accession == filing.accession
    assert res.latest().accession == filing.accession
    assert payload_loads == []
    assert filing.raw() == b"<html>Sample filing content</html>"
    assert payload_loads == [filing.primary_sha256]

    df = res.to_df()
    assert len(df) == 1
    assert "accession" in df.columns
    assert res.to_arrow().num_rows == 1
    assert res.sql("SELECT count(*) AS n FROM joined").limit(1).fetchall()[0][0] == 1
    assert len(res.attachments_df().columns) == 9
    assert len(res.exhibits().columns) == 8
    assert len(res.linkbases_df().columns) == 6
    assert len(res.staged_df().columns) == 8
    assert len(res.joined_df().columns) == 8
    assert len(res.exhibits("21").columns) == 8
    assert len(res.filter(form="10-Q")) == 0
    assert len(res.filter(date="2023")) == 0
    assert len(res.filter(limit=0)) == 0
    assert len(res.cofilers()) == 1

    empty = query_filings_from_snapshot(
        tmp_path, snapshot_id_or_tag="main", forms=("10-Q",)
    )
    assert len(empty) == 0
    assert list(empty.to_df().columns) == list(df.columns)
    with pytest.raises(IndexError):
        _ = empty[-1]
    assert (
        len(
            query_filings_from_snapshot(
                tmp_path, snapshot_id_or_tag="main", ciks=("0000000999",)
            )
        )
        == 0
    )
    assert (
        len(
            query_filings_from_snapshot(
                tmp_path, snapshot_id_or_tag="main", dates=DateRange.year(2023)
            )
        )
        == 0
    )
    assert (
        len(query_filings_from_snapshot(tmp_path, snapshot_id_or_tag="main", limit=0))
        == 0
    )


def test_facade_snapshot_access_and_tag(tmp_path: Path) -> None:
    """Verify Edgar.fetch(mode='snapshot') and Edgar.from_snapshot() via tags."""
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")

    edgar = Edgar(artifacts_root=tmp_path)
    edgar.snapshots.tag("prod-v1", pub.snapshot_id)

    res_main = edgar.fetch(mode="snapshot", snapshot="main")
    assert len(res_main) == 1
    assert res_main[0].form == "10-K"

    res_tag = edgar.from_snapshot("prod-v1")
    assert len(res_tag) == 1
    assert res_tag[0].raw() == b"<html>Sample filing content</html>"


def test_snapshot_views_exhibit_agreement(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    publish_acquisition_run(paths, run_id, branch_name="main")

    res = query_filings_from_snapshot(tmp_path, snapshot_id_or_tag="main")
    idx = res.attachments_df()
    exhibits = res.exhibits()
    flagged = {(r.accession, r.filename) for r in idx.itertuples() if r.is_exhibit}
    members = {(r.accession, r.filename) for r in exhibits.itertuples()}
    assert members == flagged
    for r in idx.itertuples():
        assert is_exhibit_attachment(r.document_type, r.filename) == bool(r.is_exhibit)


def test_is_exhibit_sql_matches_python() -> None:
    pairs = [
        ("EX-21", "doc.htm"),
        ("ex-99.1", "press.htm"),
        ("10-K", "ex99.htm"),
        ("10-K", "aapl_ex21.htm"),
        ("10-K", "report.htm"),
        ("", "exhibit10.htm"),
        ("GRAPHIC", "chart.png"),
    ]
    con = connect()
    con.execute("CREATE TEMP TABLE pairs (document_type VARCHAR, filename VARCHAR)")
    con.executemany("INSERT INTO pairs VALUES (?, ?)", pairs)
    predicate = is_exhibit_sql("document_type", "filename")
    rows = con.execute(
        f"SELECT document_type, filename, {predicate} FROM pairs"
    ).fetchall()
    assert len(rows) == len(pairs)
    for doc_type, filename, sql_flag in rows:
        assert bool(sql_flag) == is_exhibit_attachment(doc_type, filename)


def test_snapshot_attachments_hydrate_from_canonical_row(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")

    from edgar_sec.apps.client.snapshots import SnapshotSession

    session = SnapshotSession(tmp_path, pub.snapshot_id)
    attachments = session.load_attachments("0000000001-24-000001")
    assert len(attachments) == 1
    att = attachments[0]
    assert att.filename == "report.htm"
    assert att.sequence == 0
    assert isinstance(att.sequence, int)
    assert att.entry_id is None
    assert att.table_kind is None
    assert att.description is None
    assert att.size == len(b"<html>Sample filing content</html>")
    assert att.sha256 == sha256_bytes(b"<html>Sample filing content</html>")


def test_snapshot_session_caching(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")

    from edgar_sec.apps.client.snapshots import SnapshotSession

    session = SnapshotSession(tmp_path, pub.snapshot_id)
    con1, views1 = session.connection()
    con2, views2 = session.connection()
    assert con1 is con2
    assert views1 == views2
    attachments = session.load_attachments("0000320193-23-000106")
    assert isinstance(attachments, tuple)


def test_attachment_role_sql_matches_python() -> None:
    pairs = [
        (None, "10-K", "10-K"),
        (None, "10-K/A", "10-K"),
        (None, "10-KSB", "10-K"),
        (None, "10-K", "10-K/A"),
        (None, " 10-k ", "10-K"),
        (None, "10-K POS", "10-K"),
        (None, "10-K/A-POS", "10-K"),
        (None, "GRAPHIC", "10-K"),
        ("data_file", "EX-101.CAL", "10-K"),
        ("data_file", "GRAPHIC", "10-K"),
        ("data_file", None, "10-K"),
        (None, "EX-21", "10-K"),
        ("submission", "EX-99.1", "8-K"),
        (None, "SC 13G", "10-K"),
        (None, "10-K", ""),
        (None, None, "10-K"),
    ]
    con = connect()
    register_form_alias_map(con)
    con.execute(
        "CREATE TEMP TABLE pairs (table_kind VARCHAR, document_type VARCHAR, form VARCHAR)"
    )
    con.executemany("INSERT INTO pairs VALUES (?, ?, ?)", pairs)
    expr = attachment_role_sql("table_kind", "document_type", "form")
    rows = con.execute(
        f"SELECT table_kind, document_type, form, {expr} FROM pairs"
    ).fetchall()
    assert len(rows) == len(pairs)
    for table_kind, doc_type, form, sql_role in rows:
        expected = attachment_role(table_kind, doc_type, form=form)
        assert sql_role == expected, (table_kind, doc_type, form)


def test_classify_linkbase_sql_matches_python() -> None:
    pairs = [
        ("EX-101.CAL", "a.htm", ""),
        ("10-K", "a_cal.xml", ""),
        ("10-K", "doc.htm", "Calculation Linkbase"),
        ("10-K", "focal.xml", ""),
        ("EX-101.PRE", "a_cal.xml", ""),
        ("EX-102.INS", "inst.xml", ""),
        ("EX-101.INS", "a.htm", ""),
        ("10-K", "a_htm.xml", ""),
        ("10-K", "doc.htm", "XBRL Instance Document"),
        ("EX-101.SCH", "a.xml", ""),
        ("10-K", "tax.xsd", ""),
        ("10-K", "doc.htm", "Taxonomy Extension Schema"),
        ("EX-101.LAB", "a.xml", ""),
        ("EX-101.DEF", "a.xml", ""),
        ("10-K", "a-xbrl.zip", ""),
        ("10-K", "a_xbrl.zip", ""),
        ("EX-101", "a.xml", ""),
        ("10-K", "report.htm", "primary document"),
        (" EX-101.cal ", " A_CAL.XML ", ""),
        (None, None, None),
    ]
    con = connect()
    con.execute(
        "CREATE TEMP TABLE pairs (document_type VARCHAR, filename VARCHAR, description VARCHAR)"
    )
    con.executemany("INSERT INTO pairs VALUES (?, ?, ?)", pairs)
    expr = classify_linkbase_sql("document_type", "filename", "description")
    rows = con.execute(
        f"SELECT document_type, filename, description, {expr} FROM pairs"
    ).fetchall()
    assert len(rows) == len(pairs)
    for doc_type, filename, description, sql_type in rows:
        expected = classify_linkbase(doc_type or "", filename or "", description or "")
        assert sql_type == (expected.value if expected is not None else None), (
            doc_type,
            filename,
            description,
        )


def _rows(df) -> list:
    normalized = []
    for row in df.itertuples(index=False, name=None):
        normalized.append(
            tuple(None if isinstance(v, float) and v != v else v for v in row)
        )
    return sorted(normalized, key=repr)


def test_snapshot_and_fast_tables_agree(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    publish_acquisition_run(paths, run_id, branch_name="main")

    res = query_filings_from_snapshot(tmp_path, snapshot_id_or_tag="main")
    filings = list(res)
    assert _rows(res.attachments_df()) == _rows(build_index_table(filings).to_pandas())
    assert _rows(res.exhibits()) == _rows(build_exhibits_table(filings).to_pandas())
    assert _rows(res.linkbases_df()) == _rows(
        build_linkbases_table(filings).to_pandas()
    )
    staged = res.staged_df()
    fast_payload = build_payload_table(filings).to_pandas()
    assert staged["outcome"].tolist() == fast_payload["outcome"].tolist()
    assert staged["body_sha256"].tolist() == fast_payload["body_sha256"].tolist()


def test_snapshot_staged_uses_real_target_id(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, sha = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")

    res = query_filings_from_snapshot(tmp_path, snapshot_id_or_tag="main")
    staged = res.staged_df()
    assert len(staged) == 1
    row = staged.iloc[0]
    assert row["outcome"] == "acquired"
    assert row["body_sha256"] == sha
    assert row["body_byte_size"] == len(b"<html>Sample filing content</html>")

    from edgar_sec.apps.client.snapshots import SnapshotSession

    session = SnapshotSession(tmp_path, pub.snapshot_id)
    con, views = session.connection()
    target_ids = {
        r[0]
        for r in con.execute(
            f"SELECT target_id FROM {sql_identifier(views['target_results'])}"
        ).fetchall()
    }
    assert row["target_id"] in target_ids


def test_snapshot_attachment_state_and_content(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, "run-1")
    pub = publish_acquisition_run(paths, run_id, branch_name="main")

    from edgar_sec.apps.client.snapshots import SnapshotSession

    session = SnapshotSession(tmp_path, pub.snapshot_id)
    attachments = session.load_attachments("0000000001-24-000001")
    assert len(attachments) == 1
    att = attachments[0]
    assert att.state == "acquired"
    assert att.content() == b"<html>Sample filing content</html>"
    assert att.raw() == b"<html>Sample filing content</html>"
    rendered = att.rendered_text()
    assert rendered is not None
    assert "Sample filing content" in rendered


def test_snapshot_attachment_not_acquired_is_explicit(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(
        tmp_path, "run-1", target_outcome="failed", with_payload=False
    )
    pub = publish_acquisition_run(paths, run_id, branch_name="main", allow_errors=True)

    from edgar_sec.apps.client.snapshots import SnapshotSession

    session = SnapshotSession(tmp_path, pub.snapshot_id)
    attachments = session.load_attachments("0000000001-24-000001")
    assert len(attachments) == 1
    att = attachments[0]
    assert att.state == "not_acquired"
    assert att.content() is None
    assert att.rendered_text() is None
