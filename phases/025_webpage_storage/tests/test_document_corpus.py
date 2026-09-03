"""Contract tests for the Phase 025 document corpus and review workflow."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from defs.sql import DoNothing, insert_values, make_sql_executor
from defs.storage import pa, write_table_atomic

corpus = importlib.import_module("phases.025_webpage_storage.testing.corpus")
paths_mod = importlib.import_module("phases.025_webpage_storage.testing.paths")
review = importlib.import_module("phases.025_webpage_storage.testing.review")
schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
promoter = importlib.import_module(
    "phases.025_webpage_storage.tools.promote_document_corpus"
)
expectation_promoter = importlib.import_module(
    "phases.025_webpage_storage.tools.promote_document_expectations"
)


def _record(
    document_id: str = "doc-1",
    raw: bytes = b"First paragraph.\n",
    path: str = "document.txt",
) -> dict:
    return {
        "document_id": document_id,
        "accession": "000000000100000001",
        "document_path": path,
        "mime_type": "text/plain",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bytes": raw,
        "expected_output": None,
        "expected_metadata": None,
        "review_status": "pending",
        "review_notes": None,
    }


def _write_corpus(path: Path, records: list[dict]) -> None:
    write_table_atomic(
        pa.Table.from_pylist(records, schema=corpus.DOCUMENT_CORPUS_SCHEMA),
        path,
        expected_rows=len(records),
        expected_schema=corpus.DOCUMENT_CORPUS_SCHEMA,
    )


def test_document_corpus_loader_and_category_filter(tmp_path: Path) -> None:
    corpus_path = tmp_path / "document_corpus.parquet"
    _write_corpus(
        corpus_path,
        [_record(), _record("doc-2", b"<html><body>Text</body></html>", "doc.htm")],
    )

    records = corpus.load_document_corpus(corpus_path)
    assert [record["document_id"] for record in records] == ["doc-1", "doc-2"]
    assert (
        corpus.find_document_cases(
            ids=["doc-2"], categories=["html_source"], path=corpus_path
        )[0]["document_id"]
        == "doc-2"
    )


def test_document_review_artifacts_capture_current_output_and_debug(
    tmp_path: Path,
) -> None:
    record = _record()
    result = review.run_document_case(record)
    entry = review.write_review_artifacts(result, tmp_path / "doc-1")

    assert entry["document_id"] == "doc-1"
    assert (tmp_path / "doc-1" / "doc-1.txt").is_file()
    assert (tmp_path / "doc-1" / "doc-1.analysis.json").is_file()
    analysis = json.loads((tmp_path / "doc-1" / "doc-1.analysis.json").read_text())
    assert "source_text" not in analysis
    assert "CURRENT NORMALIZED OUTPUT" in (tmp_path / "doc-1" / "doc-1.txt").read_text()


def test_document_review_html_artifact_is_sanitized(tmp_path: Path) -> None:
    raw = b"<html><body><script>alert(1)</script><p>Visible</p></body></html>"
    result = review.run_document_case(_record(path="doc.htm", raw=raw))
    review.write_review_artifacts(result, tmp_path / "doc-htm")
    rendered = (tmp_path / "doc-htm" / "doc-1.html").read_text()
    assert "alert(1)" not in rendered
    assert "Visible" in rendered


def test_expectation_promotion_is_explicit_and_source_stable(tmp_path: Path) -> None:
    corpus_path = tmp_path / "document_corpus.parquet"
    _write_corpus(corpus_path, [_record()])

    assert expectation_promoter.promote(corpus_path, ["doc-1"]) == 1
    promoted = corpus.load_document_corpus(corpus_path)[0]
    assert promoted["review_status"] == "accepted"
    assert promoted["expected_output"] is not None
    assert promoted["expected_metadata"] is not None


def test_deferred_expectation_promotion_records_current_behavior(
    tmp_path: Path,
) -> None:
    corpus_path = tmp_path / "document_corpus.parquet"
    _write_corpus(corpus_path, [_record()])

    assert (
        expectation_promoter.promote(
            corpus_path,
            ["doc-1"],
            status="accepted_current_behavior",
            deferred=["paragraph_healing"],
        )
        == 1
    )
    promoted = corpus.load_document_corpus(corpus_path)[0]
    assert promoted["review_status"] == "accepted_current_behavior"
    assert json.loads(promoted["expected_metadata"])["deferred"] == [
        "paragraph_healing"
    ]


def test_fixture_id_promotion_decompresses_and_verifies_source(tmp_path: Path) -> None:
    db_path = tmp_path / "fixture.sqlite"
    db_path.touch()
    executor = make_sql_executor(db_path, dialect="sqlite")
    try:
        schemas.create_schema(executor, schemas.chunk_ddl())
        raw = b"fixture source\n"
        blob = schemas.build_blob("acc-1", "doc.txt", raw)
        executor.transaction(
            (
                executor.compiler.compile(
                    insert_values(
                        schemas.DOCUMENT_BLOBS_TABLE,
                        blob.to_row(),
                        on_conflict=DoNothing(),
                    )
                ),
            )
        )
    finally:
        executor.close()
    fixture = paths_mod.FixturePaths(tmp_path, "fixture-test", dialect="sqlite")
    fixture.manifest_path.write_text(
        json.dumps(
            {
                "fixture_id": "fixture-test",
                "storage_format": "sqlite",
                "fixture_manifest_schema_version": 1,
            }
        )
    )

    records = promoter.build_records(fixture)
    assert records[0]["source_bytes"] == raw
    assert records[0]["source_sha256"] == hashlib.sha256(raw).hexdigest()


def test_fixture_manifest_must_identify_sqlite_fixture(tmp_path: Path) -> None:
    fixture = paths_mod.FixturePaths(tmp_path, "fixture-test", dialect="sqlite")
    fixture.db_path.touch()
    fixture.manifest_path.write_text(
        json.dumps({"fixture_id": "other", "storage_format": "sqlite"})
    )
    with pytest.raises(ValueError, match="different fixture ID"):
        promoter._load_fixture_manifest(fixture)

    fixture.manifest_path.write_text(
        json.dumps({"fixture_id": "fixture-test", "storage_format": "parquet"})
    )
    with pytest.raises(ValueError, match="SQLite fixture"):
        promoter._load_fixture_manifest(fixture)


def test_corpus_path_version_validation_and_missing_lookup(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        paths_mod.document_corpus_path("corpus-one")
    with pytest.raises(FileNotFoundError):
        paths_mod.find_document_corpus("v99")
