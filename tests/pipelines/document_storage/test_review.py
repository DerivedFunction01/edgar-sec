"""Tests for comparing two review runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.pipelines.document_storage.review import (
    ADDED,
    CHANGED,
    METADATA_ONLY,
    REMOVED,
    SUMMARY_NAME,
    UNCHANGED,
    ReviewDiffError,
    compare_review_runs,
    load_run_manifest,
)


def _run(
    root: Path,
    name: str,
    documents: dict[str, str],
    *,
    fixture_id: str = "fix-1",
    source_hashes: dict[str, str] | None = None,
    extra: dict[str, dict[str, object]] | None = None,
) -> Path:
    """Write a minimal review run: one case per document, plus a manifest."""
    run = root / name
    (run / "cases").mkdir(parents=True, exist_ok=True)
    entries = []
    for document_id, text in documents.items():
        case_dir = run / "cases" / document_id
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / f"{document_id}.txt").write_text(text, encoding="utf-8")
        entry = {
            "accession": "0001234567-11-000001",
            "current_output_sha256": "ignored",
            "document_id": document_id,
            "document_path": f"{document_id}.htm",
            "fixture_id": fixture_id,
            "form": "10-K",
            "representation": "html",
            "source_sha256": (source_hashes or {}).get(document_id, "a" * 64),
        }
        if extra and document_id in extra:
            entry.update(extra[document_id])
        entries.append(entry)
    (run / "review_manifest.jsonl").write_text(
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in entries),
        encoding="utf-8",
    )
    return run


def test_identical_runs_report_no_changes(tmp_path: Path) -> None:
    documents = {"doc-a": "alpha\n", "doc-b": "beta\n"}
    base = _run(tmp_path, "run-a", documents)
    new = _run(tmp_path, "run-b", documents)
    result = compare_review_runs(base, new, tmp_path / "diff")
    assert not result.has_changes
    assert result.counts == {UNCHANGED: 2}
    assert (tmp_path / "diff" / SUMMARY_NAME).is_file()


def test_changed_text_produces_a_patch_and_html_diff(tmp_path: Path) -> None:
    base = _run(tmp_path, "run-a", {"doc-a": "one\ntwo\n"})
    new = _run(tmp_path, "run-b", {"doc-a": "one\nthree\n"})
    result = compare_review_runs(base, new, tmp_path / "diff")
    assert result.has_changes
    changed = result.changed()
    assert len(changed) == 1
    document = changed[0]
    assert document.status == CHANGED
    assert (document.added_lines, document.removed_lines) == (1, 1)
    patch = document.patch_path.read_text(encoding="utf-8")
    assert "-two" in patch
    assert "+three" in patch
    assert document.html_path.is_file()


def test_added_and_removed_documents_are_classified(tmp_path: Path) -> None:
    base = _run(tmp_path, "run-a", {"doc-a": "a\n", "doc-b": "b\n"})
    new = _run(tmp_path, "run-b", {"doc-b": "b\n", "doc-c": "c\n"})
    result = compare_review_runs(base, new, tmp_path / "diff")
    statuses = {item.document_id: item.status for item in result.documents}
    assert statuses == {"doc-a": REMOVED, "doc-b": UNCHANGED, "doc-c": ADDED}
    assert result.has_changes


def test_metadata_change_is_reported_even_when_text_is_identical(
    tmp_path: Path,
) -> None:
    """A behavioural change the text diff cannot show must still surface."""
    base = _run(tmp_path, "run-a", {"doc-a": "same\n"})
    new = _run(
        tmp_path,
        "run-b",
        {"doc-a": "same\n"},
        extra={"doc-a": {"processor_fingerprint": "normalizer:v2"}},
    )
    result = compare_review_runs(base, new, tmp_path / "diff")
    assert result.counts == {METADATA_ONLY: 1}
    assert result.has_changes


def test_changed_source_is_flagged_separately_from_text_changes(
    tmp_path: Path,
) -> None:
    """A re-filled fixture makes every output diff for that document unreadable."""
    base = _run(
        tmp_path, "run-a", {"doc-a": "one\n"}, source_hashes={"doc-a": "a" * 64}
    )
    new = _run(tmp_path, "run-b", {"doc-a": "two\n"}, source_hashes={"doc-a": "b" * 64})
    result = compare_review_runs(base, new, tmp_path / "diff")
    document = result.changed()[0]
    assert document.status == CHANGED
    assert document.source_changed is True
    summary = (tmp_path / "diff" / SUMMARY_NAME).read_text(encoding="utf-8")
    assert "re-filled between runs" in summary
    assert "doc-a" in summary


def test_different_fixtures_are_called_out(tmp_path: Path) -> None:
    base = _run(tmp_path, "run-a", {"doc-a": "a\n"}, fixture_id="fix-1")
    new = _run(tmp_path, "run-b", {"doc-a": "a\n"}, fixture_id="fix-2")
    result = compare_review_runs(base, new, tmp_path / "diff")
    assert result.fixture_mismatch == "base=fix-1 new=fix-2"
    assert "different fixtures" in (
        (tmp_path / "diff" / SUMMARY_NAME).read_text(encoding="utf-8")
    )


def test_comparing_a_run_with_itself_is_refused(tmp_path: Path) -> None:
    """A self-comparison would be a clean diff that proves nothing."""
    run = _run(tmp_path, "run-a", {"doc-a": "a\n"})
    with pytest.raises(ReviewDiffError, match="same review run"):
        compare_review_runs(run, run, tmp_path / "diff")


def test_missing_manifest_is_rejected_with_a_clear_message(tmp_path: Path) -> None:
    empty = tmp_path / "not-a-run"
    empty.mkdir()
    good = _run(tmp_path, "run-b", {"doc-a": "a\n"})
    with pytest.raises(ReviewDiffError, match="not a review run"):
        compare_review_runs(empty, good, tmp_path / "diff")


def test_malformed_manifest_line_names_its_line(tmp_path: Path) -> None:
    run = _run(tmp_path, "run-a", {"doc-a": "a\n"})
    manifest = run / "review_manifest.jsonl"
    manifest.write_text('{"document_id": "doc-a"}\nnot json\n', encoding="utf-8")
    with pytest.raises(ReviewDiffError, match=r":2 is not valid JSON"):
        load_run_manifest(run)


def test_repeated_document_id_is_rejected(tmp_path: Path) -> None:
    run = _run(tmp_path, "run-a", {"doc-a": "a\n"})
    manifest = run / "review_manifest.jsonl"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    manifest.write_text("\n".join(lines + lines) + "\n", encoding="utf-8")
    with pytest.raises(ReviewDiffError, match="repeats document"):
        load_run_manifest(run)


def test_non_empty_output_is_refused(tmp_path: Path) -> None:
    base = _run(tmp_path, "run-a", {"doc-a": "a\n"})
    new = _run(tmp_path, "run-b", {"doc-a": "b\n"})
    output = tmp_path / "diff"
    output.mkdir()
    (output / "stale").write_text("x", encoding="utf-8")
    with pytest.raises(ReviewDiffError, match="already contains artifacts"):
        compare_review_runs(base, new, output)


def test_manifest_schema_differences_are_not_reported_as_changes(
    tmp_path: Path,
) -> None:
    """A field present in one manifest and absent in the other is not a change.

    Marker and table counts are no longer computed, so comparing against a run
    that carried them would otherwise report every document as metadata-only
    changed and bury the real signal.
    """
    base = _run(
        tmp_path, "run-a", {"doc-a": "same\n"}, extra={"doc-a": {"marker_count": 4}}
    )
    new = _run(tmp_path, "run-b", {"doc-a": "same\n"})
    result = compare_review_runs(base, new, tmp_path / "diff")
    assert not result.has_changes
    assert result.counts == {UNCHANGED: 1}


def test_json_report_carries_counts_and_documents(tmp_path: Path) -> None:
    base = _run(tmp_path, "run-a", {"doc-a": "a\n"})
    new = _run(tmp_path, "run-b", {"doc-a": "b\n"})
    payload = compare_review_runs(base, new, tmp_path / "diff").to_dict()
    assert payload["counts"] == {CHANGED: 1}
    assert payload["documents"][0]["document_id"] == "doc-a"
    assert payload["base"].endswith("run-a")
