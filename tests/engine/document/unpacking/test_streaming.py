"""Exact-sequence SGML extraction from bounded file reads."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from edgar_sec.engine.document.unpacking.streaming import (
    BundleExtraction,
    BundleExtractionFailure,
    extract_bundle_sequence,
)
from edgar_sec.engine.document.unpacking.unpacker import (
    extract_target_sub_document_selection,
)


def _document(
    sequence: str | None,
    body: bytes = b"body",
    *,
    filename: str = "part.htm",
    document_type: str = "10-K",
    length: str | None = None,
) -> bytes:
    sequence_tag = b"" if sequence is None else f"<SEQUENCE>{sequence}\n".encode()
    length_tag = b"" if length is None else f"<LENGTH>{length}\n".encode()
    return (
        b"<DOCUMENT>\n<TYPE>"
        + document_type.encode()
        + b"\n"
        + sequence_tag
        + b"<FILENAME>"
        + filename.encode()
        + b"\n"
        + length_tag
        + b"<TEXT>"
        + body
        + b"</TEXT>\n</DOCUMENT>\n"
    )


def _extract(tmp_path: Path, source_bytes: bytes, sequence: int = 2, **kwargs):
    source = tmp_path / "submission.txt"
    destination = tmp_path / "selected.bin"
    source.write_bytes(source_bytes)
    result = extract_bundle_sequence(source, sequence, destination, **kwargs)
    return result, destination, source_bytes


def test_extracts_exact_body_and_reports_both_digests(tmp_path: Path) -> None:
    body = b"\r\n  filing\xff\x00 \n"
    source_bytes = _document("1", b"sibling") + _document(
        "2", body, length=str(len(body))
    )
    result, destination, source_bytes = _extract(tmp_path, source_bytes)

    assert isinstance(result, BundleExtraction)
    assert destination.read_bytes() == body
    assert result.body_size == len(body)
    assert result.body_sha256 == hashlib.sha256(body).hexdigest()
    assert result.source_size == len(source_bytes)
    assert result.source_sha256 == hashlib.sha256(source_bytes).hexdigest()
    assert result.selected.sequence == 2
    assert result.selected.filename == "part.htm"
    assert result.document_count == 2


def test_recognizes_all_control_tags_split_across_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "edgar_sec.engine.document.unpacking.streaming.DEFAULT_IO_CHUNK_SIZE", 3
    )
    source_bytes = _document("1", b"first") + _document("2", b"exact")
    result, destination, _ = _extract(tmp_path, source_bytes)

    assert isinstance(result, BundleExtraction)
    assert destination.read_bytes() == b"exact"


def test_compares_optional_header_metadata_and_source_digest(tmp_path: Path) -> None:
    source_bytes = _document("2", b"body", filename="target.htm")
    result, destination, _ = _extract(
        tmp_path,
        source_bytes,
        expected_filename="target.htm",
        expected_document_type="10-k",
        expected_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
    )

    assert isinstance(result, BundleExtraction)
    assert destination.exists()


def test_matches_small_fixture_byte_parser_oracle(tmp_path: Path) -> None:
    source_bytes = _document("2", b"oracle body")
    oracle = extract_target_sub_document_selection(source_bytes, target_types=["10-K"])
    assert oracle is not None
    result, destination, _ = _extract(tmp_path, source_bytes)

    assert isinstance(result, BundleExtraction)
    assert destination.read_bytes() == oracle.payload


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"plain text", "not_sgml"),
        (b"<DOCUMENT><SEQUENCE>2<TEXT>x</TEXT>", "malformed_delimiters"),
        (_document(None), "missing_sequence"),
        (_document("two"), "invalid_sequence"),
        (_document("1"), "sequence_not_found"),
        (_document("2", b"first") + _document("2", b"second"), "duplicate_sequence"),
        (_document("2", b"body", length="-1"), "invalid_length"),
        (_document("2", b"body", length="3"), "length_mismatch"),
        (_document("2", b"body", length="5"), "length_out_of_bounds"),
        (
            _document("1", b"sibling", length="1") + _document("2"),
            "length_mismatch",
        ),
        (b"<DOCUMENT><SEQUENCE>2</DOCUMENT>", "missing_text"),
    ],
)
def test_typed_failures_remove_output(
    tmp_path: Path, payload: bytes, code: str
) -> None:
    result, destination, source_bytes = _extract(tmp_path, payload)

    assert isinstance(result, BundleExtractionFailure)
    assert result.code == code
    assert result.source_sha256 == hashlib.sha256(source_bytes).hexdigest()
    assert not destination.exists()


@pytest.mark.parametrize(
    "metadata",
    [
        {"expected_filename": "other.htm"},
        {"expected_document_type": "8-K"},
        {"expected_source_sha256": "0" * 64},
    ],
)
def test_source_mismatch_removes_output(
    tmp_path: Path, metadata: dict[str, str]
) -> None:
    result, destination, _ = _extract(
        tmp_path, _document("2", b"tentative"), **metadata
    )

    assert isinstance(result, BundleExtractionFailure)
    assert result.code == "source_mismatch"
    assert not destination.exists()


@pytest.mark.parametrize("sequence", [0, -1, True, False, 2.0])
def test_rejects_invalid_requested_sequence_without_creating_output(
    tmp_path: Path, sequence: int
) -> None:
    source = tmp_path / "submission.txt"
    destination = tmp_path / "selected.bin"
    source.write_bytes(_document("2"))

    result = extract_bundle_sequence(source, sequence, destination)  # type: ignore[arg-type]

    assert isinstance(result, BundleExtractionFailure)
    assert result.code == "invalid_sequence"
    assert not destination.exists()


def test_source_read_error_is_typed_and_leaves_no_output(tmp_path: Path) -> None:
    result = extract_bundle_sequence(
        tmp_path / "missing.txt", 2, tmp_path / "selected.bin"
    )

    assert isinstance(result, BundleExtractionFailure)
    assert result.code == "io_error"
    assert not (tmp_path / "selected.bin").exists()


def test_duplicate_discovered_after_tentative_write_removes_partial_output(
    tmp_path: Path,
) -> None:
    payload = _document("2", b"tentative bytes") + _document("2", b"duplicate")
    result, destination, _ = _extract(tmp_path, payload)

    assert isinstance(result, BundleExtractionFailure)
    assert result.code == "duplicate_sequence"
    assert result.matching_sequences == 2
    assert not destination.exists()


def test_large_unselected_body_uses_bounded_source_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunk_size = 4096
    monkeypatch.setattr(
        "edgar_sec.engine.document.unpacking.streaming.DEFAULT_IO_CHUNK_SIZE",
        chunk_size,
    )
    source = tmp_path / "submission.txt"
    destination = tmp_path / "selected.bin"
    sibling_body = b"z" * (chunk_size * 300)
    source.write_bytes(_document("1", sibling_body) + _document("2", b"selected"))
    read_sizes: list[int] = []
    original_open = Path.open

    class ReadTracker:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def read(self, size: int = -1):
            read_sizes.append(size)
            return self.wrapped.read(size)

    def tracked_open(path: Path, mode: str = "r", *args, **kwargs):
        opened = original_open(path, mode, *args, **kwargs)
        if path == source and mode == "rb":
            return ReadTracker(opened)
        return opened

    monkeypatch.setattr(Path, "open", tracked_open)
    result = extract_bundle_sequence(source, 2, destination)

    assert isinstance(result, BundleExtraction)
    assert destination.read_bytes() == b"selected"
    assert read_sizes and max(read_sizes) == chunk_size
    assert result.source_size > chunk_size * 256
