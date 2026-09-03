"""Exact golden and integrity tests for the promoted document corpus."""

from __future__ import annotations

import hashlib
import importlib
import json
from datetime import UTC, datetime

import pytest

from defs.runtime.paths import resolve_paths
from defs.testing.goldens import compare_golden_value

corpus = importlib.import_module("phases.025_webpage_storage.testing.corpus")
paths = importlib.import_module("phases.025_webpage_storage.testing.paths")
review = importlib.import_module("phases.025_webpage_storage.testing.review")


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _corpus_or_skip() -> list[dict]:
    path = paths.document_corpus_path()
    if not path.is_file():
        pytest.skip(f"document corpus has not been promoted: {path}")
    return corpus.load_document_corpus(path)


def test_document_corpus_manifest_and_source_hashes() -> None:
    path = paths.document_corpus_path()
    if not path.is_file():
        pytest.skip(f"document corpus has not been promoted: {path}")
    records = corpus.load_document_corpus(path)
    manifest = corpus.load_document_manifest()
    assert manifest["corpus_version"] == "v1"
    assert manifest["document_count"] == len(records)
    assert manifest["corpus_sha256"]
    for record in records:
        assert (
            hashlib.sha256(bytes(record["source_bytes"])).hexdigest()
            == record["source_sha256"]
        )


def test_document_review_state_validation() -> None:
    with pytest.raises(ValueError, match="invalid review status"):
        corpus.validate_review_records(
            [{"document_id": "doc-1", "review_status": "mystery"}]
        )
    with pytest.raises(ValueError, match="deferred"):
        corpus.validate_review_records(
            [
                {
                    "document_id": "doc-1",
                    "review_status": "accepted_current_behavior",
                    "expected_output": "output",
                    "expected_metadata": "{}",
                }
            ]
        )


def test_document_goldens_match_promoted_outputs() -> None:
    records = _corpus_or_skip()
    accepted = [
        record
        for record in records
        if record["review_status"] in {"accepted", "accepted_current_behavior"}
    ]
    if not accepted:
        pytest.skip("document corpus contains no accepted expectations")
    report_root = resolve_paths().test_run_root(
        "webpage_storage", "document-goldens", _run_id()
    )
    report_root.mkdir(parents=True, exist_ok=True)
    pending = len(records) - len(accepted)
    print(f"DOCUMENT CORPUS: accepted={len(accepted)} pending={pending}")
    divergent: list[str] = []
    for record in accepted:
        assert record["expected_output"] is not None
        result = review.run_document_case(record)
        fixture_id = str(record["document_id"])
        if not compare_golden_value(
            result.normalized_text,
            record["expected_output"],
            report_root,
            fixture_id,
            {
                "source_sha256": record["source_sha256"],
                "document_path": record["document_path"],
            },
        ):
            divergent.append(fixture_id)
        expected_metadata = record.get("expected_metadata")
        if expected_metadata:
            expected = json.loads(expected_metadata)
            if record["review_status"] == "accepted_current_behavior":
                expected.pop("deferred", None)
            assert expected == review.stable_expected_metadata(result)
    assert not divergent, (
        f"document goldens diverged: {divergent}; report={report_root}"
    )
