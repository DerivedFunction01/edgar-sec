"""Tests for offline fixture builder utility."""

from __future__ import annotations

import importlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from defs.runtime.paths import resolve_paths
from defs.sql import Select, SqlDialect, Table, col, make_sql_executor

fixture_builder = importlib.import_module(
    "phases.025_webpage_storage.core.fixture_builder"
)
schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
cli = importlib.import_module("phases.025_webpage_storage.cli")


@dataclass
class FakeHttpClient:
    payloads: dict[str, bytes]

    def get_bytes(self, url: str) -> bytes:
        if url in self.payloads:
            return self.payloads[url]
        raise ValueError(f"404 Not Found: {url}")


def test_fill_fixture_populates_sqlite_directly(phase02_bundle: Path, tmp_path: Path):
    fixture_id = f"test-fix-{uuid.uuid4().hex[:8]}"
    fake_client = FakeHttpClient(
        {
            "https://www.sec.gov/Archives/000000000100000001/10k.htm": b"<html>doc1</html>",
            "https://www.sec.gov/Archives/000000000100000001/10k2.htm": b"<html>doc2</html>",
        }
    )

    result = fixture_builder.fill_fixture(
        phase02_bundle,
        fixture_id=fixture_id,
        http_client=fake_client,
    )

    assert result["fixture_id"] == fixture_id
    assert result["newly_fetched"] == 2
    assert result["total_persisted"] == 2

    # Verify SQLite database directly
    db_path = resolve_paths().fixture(fixture_id, dialect="sqlite").db_path
    assert db_path.is_file()

    executor = make_sql_executor(db_path, dialect=SqlDialect.SQLITE)
    try:
        blobs = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(schemas.DOCUMENT_BLOBS_TABLE),
                    projection=(col("doc_id"), col("raw_payload")),
                )
            )
        )
    finally:
        executor.close()

    assert len(blobs) == 2
    decompressed = [schemas.decompress_payload(b["raw_payload"]) for b in blobs]
    assert b"<html>doc1</html>" in decompressed
    assert b"<html>doc2</html>" in decompressed


def test_cli_fill_fixture_command(
    phase02_bundle: Path, capsys: pytest.CaptureFixture[str]
):
    fixture_id = f"cli-fix-{uuid.uuid4().hex[:8]}"
    # Fill with limit 1
    code = cli.main(
        [
            "fill-fixture",
            "--plan-dir",
            str(phase02_bundle),
            "--fixture-id",
            fixture_id,
            "--limit",
            "1",
            "--no-progress",
        ]
    )
    # The default http client might fail on mock URLs, but the command runs cleanly
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["fixture_id"] == fixture_id
    assert data["target_locators"] == 1
