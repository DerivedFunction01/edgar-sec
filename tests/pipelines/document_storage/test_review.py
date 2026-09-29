"""Tests for the review bundle harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence
from edgar_sec.domain.identity import Cik
from edgar_sec.infra.storage.document_parquet import write_chunk_snapshot
from edgar_sec.pipelines.document_storage.review import (
    EXCERPT_CHARS,
    OUTCOME_STRATA,
    REVIEW_MANIFEST_NAME,
    ReviewError,
    classify_outcome,
    render_review_set,
    select_bundles,
)

ACCESSION = "0001234567-11-000001"


def _artifact(path: Path, rows: list[tuple[str, str, str, str]]) -> Path:
    occurrences = []
    raw = {}
    texts = {}
    statuses = {}
    errors = {}
    for document_path, form, status, text in rows:
        locator = DocumentLocator.from_parts(ACCESSION, document_path)
        occurrence = FilingOccurrence(
            occurrence_id=f"occ-{locator.document_locator_key[:8]}",
            source_cik=Cik.from_raw("1234567"),
            accession=locator.accession,
            document_path=document_path,
            form=form,
            filing_date="2012-02-15",
            report_date=None,
            doc_id=locator.document_locator_key,
        )
        occurrences.append(occurrence)
        raw[locator.document_locator_key] = document_path.encode()
        texts[occurrence.occurrence_id] = text
        statuses[occurrence.occurrence_id] = status
        if status != "ok":
            errors[occurrence.occurrence_id] = "acquisition failed"
    write_chunk_snapshot(path, occurrences, raw, texts, statuses, errors)
    return path


# --- outcome classification ----------------------------------------------


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"status": "failed", "normalized_text": "x", "form": "10-K"}, "failed"),
        ({"status": "missing", "normalized_text": "", "form": "10-K"}, "missing"),
        ({"status": "ok", "normalized_text": "   "}, "empty_text"),
        ({"status": "ok", "normalized_text": "body"}, "ok"),
    ],
)
def test_outcome_classification(row: dict, expected: str) -> None:
    assert classify_outcome(row) == expected


def test_failure_outranks_empty_text() -> None:
    assert classify_outcome({"status": "failed", "normalized_text": ""}) == "failed"


# --- selection ------------------------------------------------------------


def _row(key: str, outcome_status: str, text: str = "body") -> dict:
    return {
        "document_locator_key": key,
        "accession": ACCESSION,
        "document_path": f"{key}.htm",
        "status": outcome_status,
        "normalized_text": text,
    }


def test_selection_prefers_surprising_outcomes() -> None:
    rows = [_row(f"ok{i}", "ok") for i in range(50)]
    rows.append(_row("bad", "failed"))
    bundles, _skipped = select_bundles(rows, limit=5)
    assert len(bundles) == 5
    assert bundles[0].outcome == "failed"
    assert {bundle.outcome for bundle in bundles} == {"failed", "ok"}


def test_selection_is_deterministic() -> None:
    rows = [_row(f"k{i:03d}", "ok") for i in range(20)]
    first, _ = select_bundles(rows, limit=5)
    second, _ = select_bundles(list(reversed(rows)), limit=5)
    assert [b.document_locator_key for b in first] == [
        b.document_locator_key for b in second
    ]


def test_selection_reports_what_it_left_out() -> None:
    rows = [_row(f"k{i}", "ok") for i in range(10)]
    bundles, skipped = select_bundles(rows, limit=3)
    assert len(bundles) == 3
    assert skipped == 7


def test_zero_limit_selects_nothing() -> None:
    bundles, skipped = select_bundles([_row("a", "ok")], limit=0)
    assert bundles == []
    assert skipped == 1


def test_every_stratum_is_represented_when_budget_allows() -> None:
    rows = [
        _row("f", "failed"),
        _row("m", "missing"),
        _row("e", "ok", text="   "),
        _row("o", "ok"),
    ]
    bundles, skipped = select_bundles(rows, limit=10)
    assert skipped == 0
    assert [bundle.outcome for bundle in bundles] == list(OUTCOME_STRATA)


def test_long_text_is_truncated() -> None:
    bundles, _ = select_bundles([_row("a", "ok", text="x" * (EXCERPT_CHARS + 500))], 1)
    assert len(bundles[0].normalized_text) == EXCERPT_CHARS


# --- rendering ------------------------------------------------------------


def test_render_writes_bundles_and_a_manifest(tmp_path: Path) -> None:
    artifact = _artifact(
        tmp_path / "documents.parquet",
        [
            ("a.htm", "10-K", "ok", "alpha body"),
            ("b.htm", "10-K", "failed", ""),
        ],
    )
    out = tmp_path / "review"
    result = render_review_set(artifact_path=artifact, output_dir=out)
    assert result.rendered == 2
    assert result.skipped == 0
    assert result.errors == ()
    assert (out / REVIEW_MANIFEST_NAME).is_file()

    manifest = json.loads((out / REVIEW_MANIFEST_NAME).read_text())
    assert manifest["rendered"] == 2
    assert len(manifest["bundles"]) == 2
    assert {b["outcome"] for b in manifest["bundles"]} == {"ok", "failed"}


def test_bundle_files_are_self_contained_json(tmp_path: Path) -> None:
    artifact = _artifact(
        tmp_path / "documents.parquet", [("a.htm", "10-K", "ok", "body")]
    )
    out = tmp_path / "review"
    render_review_set(artifact_path=artifact, output_dir=out)
    bundles = [p for p in out.iterdir() if p.name != REVIEW_MANIFEST_NAME]
    assert len(bundles) == 1
    payload = json.loads(bundles[0].read_text())
    assert payload["document_path"] == "a.htm"
    assert payload["normalized_text"] == "body"
    assert payload["word_count"] == 1


def test_render_respects_the_limit(tmp_path: Path) -> None:
    artifact = _artifact(
        tmp_path / "documents.parquet",
        [(f"d{i}.htm", "10-K", "ok", "body") for i in range(10)],
    )
    result = render_review_set(
        artifact_path=artifact, output_dir=tmp_path / "review", limit=3
    )
    assert result.rendered == 3
    assert result.skipped == 7


def test_render_recreates_a_missing_output_directory(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "documents.parquet", [("a.htm", "10-K", "ok", "x")])
    out = tmp_path / "nested" / "review"
    result = render_review_set(artifact_path=artifact, output_dir=out)
    assert out.is_dir()
    assert result.rendered == 1


def test_missing_artifact_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ReviewError, match="not found"):
        render_review_set(
            artifact_path=tmp_path / "absent.parquet", output_dir=tmp_path / "out"
        )


def test_render_is_repeatable(tmp_path: Path) -> None:
    artifact = _artifact(
        tmp_path / "documents.parquet",
        [("a.htm", "10-K", "ok", "alpha"), ("b.htm", "10-K", "failed", "")],
    )
    first = render_review_set(artifact_path=artifact, output_dir=tmp_path / "r1")
    second = render_review_set(artifact_path=artifact, output_dir=tmp_path / "r2")
    assert [b.document_locator_key for b in first.bundles] == [
        b.document_locator_key for b in second.bundles
    ]


def test_empty_snapshot_renders_an_empty_manifest(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "documents.parquet", [])
    out = tmp_path / "review"
    result = render_review_set(artifact_path=artifact, output_dir=out)
    assert result.rendered == 0
    manifest = json.loads((out / REVIEW_MANIFEST_NAME).read_text())
    assert manifest["rendered"] == 0
    assert manifest["bundles"] == []


def test_result_serializes_for_the_cli(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "documents.parquet", [("a.htm", "10-K", "ok", "x")])
    result = render_review_set(artifact_path=artifact, output_dir=tmp_path / "review")
    payload = result.to_dict()
    assert payload["rendered"] == 1
    assert payload["errors"] == []
    assert "output_dir" in payload


def test_review_reads_a_consolidated_part_tree(tmp_path: Path) -> None:
    """The ``current`` pointer can name a part tree, not just an assembled file.

    A run snapshot is one ``documents.parquet``; a consolidated snapshot is a
    repartitioned part tree with index and payload in separate files. A review
    that only understood the first would report "not published" for a perfectly
    good snapshot.
    """
    from edgar_sec.infra.storage.document_parts import (
        PlannedPart,
        write_index_part,
        write_payload_part,
    )
    from edgar_sec.infra.storage.manifests import SnapshotPart, write_manifest

    snapshot_dir = tmp_path / "snap-parts"
    index_part = PlannedPart(
        path="parts/index/run.parquet",
        kind="index",
        doc_ids=("d1",),
        estimated_bytes=10,
    )
    payload_part = PlannedPart(
        path="parts/payload/run.parquet",
        kind="payload",
        doc_ids=("d1",),
        estimated_bytes=10,
    )
    write_index_part(
        snapshot_dir,
        index_part,
        [
            {
                "occurrence_id": "occ-1",
                "source_cik": "1234567",
                "accession": "0001234567-11-000001",
                "form": "10-K",
                "filing_date": "2011-02-15",
                "report_date": None,
                "document_path": "a.htm",
                "doc_id": "d1",
                "mime_type": "text/plain",
                "byte_size": "5",
                "payload_file": payload_part.path,
            }
        ],
    )
    payload_entry = write_payload_part(snapshot_dir, payload_part, [("d1", "body")])
    parts = [
        SnapshotPart(
            path=index_part.path,
            kind=index_part.kind,
            doc_ids=index_part.doc_ids,
            row_count=1,
        ).to_dict(),
        payload_entry.to_dict(),
    ]
    write_manifest(
        tmp_path,
        {
            "snapshot_id": "snap-parts",
            "schema_version": "1",
            "resolved_parts": parts,
            "source_snapshot_ids": ["run-1"],
            "dataset": "document_storage",
            "phase": "025_webpage_storage",
            "logical_fingerprint": "fp",
        },
        set_current=False,
    )

    result = render_review_set(
        artifact_path=snapshot_dir, output_dir=tmp_path / "review"
    )
    assert result.rendered == 1
    assert result.bundles[0].document_path == "a.htm"
    assert result.bundles[0].normalized_text == "body"


def test_review_rejects_a_directory_without_a_manifest(tmp_path: Path) -> None:
    empty = tmp_path / "snap-empty"
    empty.mkdir()
    with pytest.raises(ReviewError, match="manifest not found"):
        render_review_set(artifact_path=empty, output_dir=tmp_path / "review")
