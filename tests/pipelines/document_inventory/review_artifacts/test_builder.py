from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.infra.storage.review.paths import (
    PIPELINE_REVIEW_MANIFEST_FILE,
    ReviewPaths,
)
from edgar_sec.pipelines.document_inventory.fixture_store.models import IndexResponseKey
from edgar_sec.pipelines.document_inventory.fixture_store.reader import (
    open_index_fixture,
)
from edgar_sec.pipelines.document_inventory.review_artifacts.builder import (
    build_review_artifacts,
)


def test_builder_writes_preview_observation_entries_and_manifest(
    tmp_path: Path, captured_fixture
) -> None:
    fixture, accession, _body = captured_fixture
    output = tmp_path / "review-one"

    result = build_review_artifacts(fixture, output, workers=1)

    assert result.exit_code == 0
    assert result.summary.total == result.summary.parsed == 1
    paths = ReviewPaths(output, PIPELINE_REVIEW_MANIFEST_FILE)
    row = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    assert row["accession"] == str(accession)
    assert row["status"] == "parsed"
    case_dir = output / row["outputs"]["source.inert.html"]["path"]
    assert (case_dir.parent / "source.inert.html").is_file()
    assert (case_dir.parent / "observations.json").is_file()
    assert (case_dir.parent / "entries.csv").is_file()
    observation = json.loads((case_dir.parent / "observations.json").read_text())
    assert observation["parser_fingerprint"]
    assert observation["entry_count"] == result.summary.entries_total


def test_replay_failure_has_no_entries_file(tmp_path: Path, captured_fixture) -> None:
    fixture, accession, _body = captured_fixture
    with open_index_fixture(fixture) as reader:
        case = next(reader.iter_cases())
    with sqlite3.connect(fixture.storage_path) as connection:
        connection.execute(
            "UPDATE index_responses SET compressed_body = ? WHERE request_url = ?",
            (b"not-zstd", case.key.request_url),
        )
    result = build_review_artifacts(fixture, tmp_path / "review-bad", workers=1)
    assert result.exit_code == 1
    assert result.summary.replay_failure == 1
    row = json.loads((tmp_path / "review-bad" / "manifest.jsonl").read_text())
    assert row["status"] == "replay_failure"
    assert row["accession"] == str(accession)
    assert row["outputs"] == {}


def test_empty_selection_and_nonempty_destination_are_refused(
    tmp_path: Path, captured_fixture
) -> None:
    fixture, _accession, _body = captured_fixture
    output = tmp_path / "empty"
    with pytest.raises(ValueError, match="selection is empty"):
        build_review_artifacts(
            fixture,
            output,
            accessions=[AccessionNumber("0000999999-26-000001")],
            workers=1,
        )
    assert not output.exists()
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep").write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError, match="new or empty"):
        build_review_artifacts(fixture, occupied, workers=1)


def test_selected_page_digest_is_pinned_and_case_path_is_stable(
    tmp_path: Path, captured_fixture
) -> None:
    fixture, accession, _body = captured_fixture
    with open_index_fixture(fixture) as reader:
        case = reader.list_cases(accession)[0]
    paths = ReviewPaths(tmp_path / "review", PIPELINE_REVIEW_MANIFEST_FILE)
    key_digest = hashlib.sha256(
        f"{case.key.request_url}\n{case.key.response_sha256}".encode("utf-8")
    ).hexdigest()[:16]
    case_id = f"{case.accession}--{key_digest}"
    first = paths.case_dir(case_id)
    second = paths.case_dir(case_id)
    assert first == second
    assert first.name.startswith(str(accession))


def test_parallel_workers_keep_manifest_order_and_case_isolation(
    tmp_path: Path, captured_multi_fixture
) -> None:
    fixture, accessions = captured_multi_fixture
    result = build_review_artifacts(fixture, tmp_path / "review-parallel", workers=2)
    lines = (tmp_path / "review-parallel" / "manifest.jsonl").read_text().splitlines()
    records = [json.loads(line) for line in lines]
    assert [record["accession"] for record in records] == list(map(str, accessions))
    assert [record["status"] for record in records] == ["parsed", "unrecognized"]
    assert result.summary.parsed == result.summary.unrecognized == 1
    key_digest = hashlib.sha256(
        f"{records[1]['request_url']}\n{records[1]['response_sha256']}".encode("utf-8")
    ).hexdigest()[:16]
    second_id = f"{accessions[1]}--{key_digest}"
    second_dir = ReviewPaths(
        tmp_path / "review-parallel", PIPELINE_REVIEW_MANIFEST_FILE
    ).case_dir(second_id)
    assert (second_dir / "source.inert.html").is_file()
    assert (second_dir / "observations.json").is_file()
    assert not (second_dir / "entries.csv").exists()
