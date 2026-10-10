"""Bounded exact-sequence extraction from SEC SGML submission files."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE

# A document header is metadata, so it is bounded independently of the read buffer.
_MAX_HEADER_SIZE = 64 * 1024
_TOKENS = (b"<DOCUMENT>", b"</DOCUMENT>", b"<TEXT>", b"</TEXT>")
_MAX_TOKEN_SIZE = max(map(len, _TOKENS))
_FIELD_PATTERNS = {
    "sequence": re.compile(rb"(?i)<SEQUENCE>\s*([^\r\n<]+)"),
    "filename": re.compile(rb"(?i)<FILENAME>\s*([^\r\n<]+)"),
    "document_type": re.compile(rb"(?i)<TYPE>\s*([^\r\n<]+)"),
    "length": re.compile(rb"(?i)<LENGTH>\s*([^\r\n<]+)"),
    "description": re.compile(rb"(?i)<DESCRIPTION>\s*([^\r\n<]+)"),
}

FailureCode = Literal[
    "not_sgml",
    "malformed_delimiters",
    "missing_sequence",
    "invalid_sequence",
    "sequence_not_found",
    "duplicate_sequence",
    "invalid_length",
    "length_mismatch",
    "length_out_of_bounds",
    "missing_text",
    "source_mismatch",
    "io_error",
]


@dataclass(frozen=True, slots=True)
class BundleDocumentHeader:
    ordinal: int
    sequence: int
    filename: str | None
    document_type: str | None
    description: str | None
    declared_length: int | None


@dataclass(frozen=True, slots=True)
class BundleExtraction:
    destination: Path
    selected: BundleDocumentHeader
    document_count: int
    source_size: int
    source_sha256: str
    body_size: int
    body_sha256: str


@dataclass(frozen=True, slots=True)
class BundleExtractionFailure:
    code: FailureCode
    matching_sequences: int
    source_sha256: str


def extract_bundle_sequence(
    source: Path,
    sequence: int,
    destination: Path,
    *,
    expected_filename: str | None = None,
    expected_document_type: str | None = None,
    expected_source_sha256: str | None = None,
) -> BundleExtraction | BundleExtractionFailure:
    """Write the exact body for one sequence, or return a typed failure."""
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
        return BundleExtractionFailure("invalid_sequence", 0, "")

    source_hash = hashlib.sha256()
    body_hash = hashlib.sha256()
    source_size = 0
    body_size = 0
    current_body_size = 0
    document_count = 0
    matching_sequences = 0
    selected: BundleDocumentHeader | None = None
    failure: FailureCode | None = None
    state = "outside"
    header = bytearray()
    current: BundleDocumentHeader | None = None
    current_is_selected = False
    body_stream = None
    pending = bytearray()

    def fail(code: FailureCode) -> None:
        nonlocal failure
        if failure is None:
            failure = code

    def consume(data: bytes) -> None:
        nonlocal body_size, current_body_size, body_stream
        if state == "header":
            remaining = _MAX_HEADER_SIZE - len(header)
            if len(data) > remaining:
                fail("malformed_delimiters")
            header.extend(data[:remaining])
        elif state == "body":
            current_body_size += len(data)
            if current_is_selected and matching_sequences == 1:
                body_hash.update(data)
                body_size += len(data)
                if body_stream is not None:
                    try:
                        body_stream.write(data)
                    except OSError:
                        fail("io_error")
                        try:
                            body_stream.close()
                        except OSError:
                            pass
                        body_stream = None

    def read_field(name: str) -> list[str]:
        values = []
        for match in _FIELD_PATTERNS[name].finditer(header):
            value = match.group(1).decode("latin-1").strip()
            if value:
                values.append(value)
        return values

    def begin_text() -> None:
        nonlocal current, current_is_selected, selected, matching_sequences
        nonlocal body_stream, body_hash, body_size, current_body_size
        sequences = read_field("sequence")
        if not sequences:
            fail("missing_sequence")
            parsed_sequence = 0
        elif len(sequences) != 1 or not sequences[0].isdecimal():
            fail("invalid_sequence")
            parsed_sequence = 0
        else:
            parsed_sequence = int(sequences[0])
            if parsed_sequence <= 0:
                fail("invalid_sequence")

        lengths = read_field("length")
        declared_length = None
        if len(lengths) > 1 or (lengths and not lengths[0].isdecimal()):
            fail("invalid_length")
        elif lengths:
            declared_length = int(lengths[0])

        filenames = read_field("filename")
        types = read_field("document_type")
        descriptions = read_field("description")
        current = BundleDocumentHeader(
            ordinal=document_count,
            sequence=parsed_sequence,
            filename=filenames[0] if len(filenames) == 1 else None,
            document_type=types[0].upper() if len(types) == 1 else None,
            description=descriptions[0] if len(descriptions) == 1 else None,
            declared_length=declared_length,
        )
        if len(filenames) > 1 or len(types) > 1 or len(descriptions) > 1:
            fail("malformed_delimiters")
        current_is_selected = parsed_sequence == sequence
        current_body_size = 0
        if current_is_selected:
            matching_sequences += 1
            if matching_sequences == 1:
                selected = current
                body_hash = hashlib.sha256()
                body_size = 0
                try:
                    body_stream = destination.open("wb")
                except OSError:
                    fail("io_error")
            else:
                fail("duplicate_sequence")
        header.clear()

    def handle(token: bytes) -> None:
        nonlocal state, document_count, current_is_selected, current
        if token == b"<DOCUMENT>":
            if state != "outside":
                fail("malformed_delimiters")
                return
            state = "header"
            document_count += 1
            header.clear()
            current = None
            current_is_selected = False
            return
        if token == b"</DOCUMENT>":
            if state == "header":
                fail("missing_text")
                state = "outside"
            elif state == "body":
                fail("missing_text")
                state = "outside"
            elif state == "after_text":
                state = "outside"
            else:
                fail("malformed_delimiters")
            if current is not None:
                _validate_length(current.declared_length, current_body_size, fail)
            current = None
            current_is_selected = False
            return
        if token == b"<TEXT>":
            if state != "header":
                fail("malformed_delimiters")
                return
            begin_text()
            state = "body"
            return
        if token == b"</TEXT>":
            if state != "body":
                fail("malformed_delimiters")
                return
            state = "after_text"

    try:
        with source.open("rb") as input_stream:
            while chunk := input_stream.read(DEFAULT_IO_CHUNK_SIZE):
                source_hash.update(chunk)
                source_size += len(chunk)
                pending.extend(chunk)
                while pending:
                    lower = pending.lower()
                    found: tuple[int, bytes] | None = None
                    for token in _TOKENS:
                        index = lower.find(token.lower())
                        if index >= 0 and (found is None or index < found[0]):
                            found = index, token
                    if found is None:
                        safe_size = len(pending) - _MAX_TOKEN_SIZE + 1
                        if safe_size <= 0:
                            break
                        consume(bytes(pending[:safe_size]))
                        del pending[:safe_size]
                        continue
                    index, token = found
                    if index:
                        consume(bytes(pending[:index]))
                    del pending[: index + len(token)]
                    handle(token)

            if pending:
                consume(bytes(pending))
                pending.clear()
            if state in ("header", "body", "after_text"):
                fail("malformed_delimiters" if state != "header" else "missing_text")
            if body_stream is not None:
                body_stream.close()
                body_stream = None
    except OSError:
        if body_stream is not None:
            try:
                body_stream.close()
            except OSError:
                pass
        _remove_destination(destination)
        return BundleExtractionFailure(
            "io_error", matching_sequences, source_hash.hexdigest()
        )

    source_sha256 = source_hash.hexdigest()
    if document_count == 0:
        fail("not_sgml")
    if matching_sequences == 0 and failure is None:
        fail("sequence_not_found")
    if matching_sequences > 1:
        failure = "duplicate_sequence"
    if selected is not None and failure is None:
        if expected_filename is not None and (
            selected.filename is None
            or selected.filename.casefold() != expected_filename.casefold()
        ):
            fail("source_mismatch")
        if expected_document_type is not None and (
            selected.document_type is None
            or selected.document_type.casefold() != expected_document_type.casefold()
        ):
            fail("source_mismatch")
    if expected_source_sha256 is not None and (
        source_sha256.casefold() != expected_source_sha256.casefold()
    ):
        fail("source_mismatch")
    if failure is not None or selected is None:
        _remove_destination(destination)
        return BundleExtractionFailure(
            failure or "sequence_not_found", matching_sequences, source_sha256
        )

    return BundleExtraction(
        destination=destination,
        selected=selected,
        document_count=document_count,
        source_size=source_size,
        source_sha256=source_sha256,
        body_size=body_size,
        body_sha256=body_hash.hexdigest(),
    )


def _validate_length(
    declared_length: int | None,
    body_size: int,
    fail: Callable[[FailureCode], None],
) -> None:
    if declared_length is None:
        return
    if declared_length > body_size:
        fail("length_out_of_bounds")
    elif declared_length != body_size:
        fail("length_mismatch")


def _remove_destination(destination: Path) -> None:
    try:
        destination.unlink(missing_ok=True)
    except OSError:
        pass
