"""Tests for filing-resolution SGML inspection in the unpacker.

The primitive parses every document header while materializing only the two bodies
the resolver keeps; the envelope itself never passes through.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.unpacking.unpacker import (
    FilingResolutionScan,
    _check_document_delimiters,
    _slice_body,
    scan_filing_bundle,
)


TYPES = ("10-K", "10-K/A", "10-K405")

BUNDLE_EXHIBIT_PRIMARY = (
    b"<SEC-DOCUMENT>\n"
    b"<SEC-HEADER>0000320193-02-000123</SEC-HEADER>\n"
    b"<TYPE>10-K\n<FILENAME>0000320193-02-000123.txt\n"
    b"<DOCUMENT>\n<TYPE>EX-21\n<SEQUENCE>1\n<FILENAME>ex21.txt\n"
    b"<DESCRIPTION>LIST OF SUBSIDIARIES\n"
    b"<TEXT>\nEXHIBIT TWENTY ONE BODY\n</TEXT>\n</DOCUMENT>\n"
    b"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>3\n<FILENAME>a10k.htm\n"
    b"<DESCRIPTION>FORM 10-K\n"
    b"<TEXT>\n<HTML><BODY>ANNUAL REPORT BODY</BODY></HTML>\n</TEXT>\n</DOCUMENT>\n"
    b"</SEC-DOCUMENT>\n"
)


def test_scan_exposes_all_headers_in_order() -> None:
    """Every document header is recorded, in envelope order, without bodies."""
    scan = scan_filing_bundle(BUNDLE_EXHIBIT_PRIMARY, "ex21.txt", TYPES)
    assert [(d.document_path, d.sequence, d.doc_type) for d in scan.documents] == [
        ("ex21.txt", 1, "EX-21"),
        ("a10k.htm", 3, "10-K"),
    ]
    assert [d.description for d in scan.documents] == [
        "LIST OF SUBSIDIARIES",
        "FORM 10-K",
    ]


def test_scan_slices_only_the_requested_body() -> None:
    """The requested body is the one from the bundle, not an envelope copy."""
    scan = scan_filing_bundle(BUNDLE_EXHIBIT_PRIMARY, "ex21.txt", TYPES)
    assert scan.requested is not None
    assert scan.requested.document_path == "ex21.txt"
    assert scan.requested.sequence == 1
    assert scan.requested.description == "LIST OF SUBSIDIARIES"
    assert scan.requested.payload == b"EXHIBIT TWENTY ONE BODY"


def test_scan_slices_only_the_primary_body() -> None:
    """The primary is the lowest accepted sequence; sibling bodies stay elided."""
    scan = scan_filing_bundle(BUNDLE_EXHIBIT_PRIMARY, "ex21.txt", TYPES)
    assert scan.primary is not None
    assert scan.primary.document_path == "a10k.htm"
    assert scan.primary.doc_type == "10-K"
    assert scan.primary.sequence == 3
    assert scan.primary.payload == b"<HTML><BODY>ANNUAL REPORT BODY</BODY></HTML>"
    # All headers are present while bodies live only in the resolved references.
    assert len(scan.documents) == 2
    assert scan.documents[0].document_path == "ex21.txt"
    assert scan.documents[1].document_path == "a10k.htm"
    assert scan.requested.document_path == "ex21.txt"
    assert scan.primary.document_path == "a10k.htm"
    assert scan.requested.payload is not None and scan.primary.payload is not None


def test_scan_request_match_is_case_insensitive_and_exact_basename() -> None:
    """Matched by basename only; a directory prefix never names a sub-document."""
    scan = scan_filing_bundle(BUNDLE_EXHIBIT_PRIMARY, "ex21.txt", TYPES)
    assert scan.requested_match_count == 1
    scan2 = scan_filing_bundle(BUNDLE_EXHIBIT_PRIMARY, "EX21.TXT", TYPES)
    assert scan2.requested_match_count == 1
    scan3 = scan_filing_bundle(BUNDLE_EXHIBIT_PRIMARY, "ex21.txt/extra", TYPES)
    assert scan3.requested_match_count == 0


def test_scan_primary_selects_lowest_valid_positive_sequence() -> None:
    """The lowest valid positive sequence wins among accepted types."""
    bundle = (
        b"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>5\n<FILENAME>z.htm\n<TEXT>x</TEXT>\n</DOCUMENT>"
        b"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>2\n<FILENAME>m.htm\n<TEXT>y</TEXT>\n</DOCUMENT>"
        b"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>1\n<FILENAME>a.htm\n<TEXT>z</TEXT>\n</DOCUMENT>"
    )
    scan = scan_filing_bundle(bundle, "a.htm", TYPES)
    assert scan.primary_sequence_tie is False
    assert scan.primary is not None and scan.primary.document_path == "a.htm"


def test_scan_primary_tie_returns_ambiguous() -> None:
    """Tied lowest accepted sequence is not disambiguated by this level."""
    tie = (
        b"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>1\n<FILENAME>a.htm\n<TEXT>x</TEXT>\n</DOCUMENT>"
        b"<DOCUMENT>\n<TYPE>10-K/A\n<SEQUENCE>1\n<FILENAME>b.htm\n<TEXT>y</TEXT>\n</DOCUMENT>"
    )
    scan = scan_filing_bundle(tie, "a.htm", TYPES)
    assert scan.primary_sequence_tie is True
    assert scan.primary is None


def test_scan_primary_missing_sequence_returns_invalid_flag() -> None:
    """An accepted type without a sequence is flagged, never silently skipped."""
    miss = (
        b"<DOCUMENT>\n<TYPE>10-K\n<FILENAME>a.htm\n<TEXT>x</TEXT>\n</DOCUMENT>"
        b"<DOCUMENT>\n<TYPE>10-K/A\n<SEQUENCE>1\n<FILENAME>b.htm\n<TEXT>y</TEXT>\n</DOCUMENT>"
    )
    scan = scan_filing_bundle(miss, "a.htm", TYPES)
    assert scan.primary_invalid_sequence is True
    assert scan.primary is not None and scan.primary.document_path == "b.htm"


def test_scan_primary_zero_and_negative_sequences_are_invalid() -> None:
    """Sequence must be a positive number; zero and negatives are invalid."""
    zero = b"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>0\n<FILENAME>a.htm\n<TEXT>x</TEXT>\n</DOCUMENT>"
    neg = b"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>-1\n<FILENAME>b.htm\n<TEXT>y</TEXT>\n</DOCUMENT>"
    combo = zero + neg
    scan = scan_filing_bundle(combo, "a.htm", TYPES)
    assert scan.primary_invalid_sequence is True
    assert scan.primary is None


def test_scan_no_matching_type_yields_no_primary() -> None:
    """Accepted types absent from the bundle produce no primary candidate."""
    no_match = (
        b"<DOCUMENT>\n<TYPE>EX-21\n<SEQUENCE>1\n<FILENAME>ex21.txt\n<TEXT>x</TEXT>\n</DOCUMENT>"
        b"<DOCUMENT>\n<TYPE>EX-99\n<SEQUENCE>2\n<FILENAME>ex99.htm\n<TEXT>y</TEXT>\n</DOCUMENT>"
    )
    scan = scan_filing_bundle(no_match, "ex21.txt", TYPES)
    assert scan.primary_sequence_tie is False
    assert scan.primary_invalid_sequence is False
    assert scan.primary is None


def test_scan_empty_payload_is_empty() -> None:
    """An empty envelope yields empty headers and no slices."""
    scan = scan_filing_bundle(b"", "a.htm", TYPES)
    assert scan.documents == ()
    assert scan.requested is None
    assert scan.primary is None
    assert scan.requested_match_count == 0
    assert scan.scan_error is None


def test_scan_nesting_is_detected() -> None:
    """A second <DOCUMENT> inside another is a structural failure."""
    nested = b"<DOCUMENT><DOCUMENT>text</DOCUMENT></DOCUMENT>"
    assert _check_document_delimiters(nested) == "nested <DOCUMENT> delimiter"


def test_scan_unbalanced_opens_are_detected() -> None:
    """An unclosed <DOCUMENT> is a structural failure."""
    assert (
        _check_document_delimiters(b"<DOCUMENT>text")
        == "unbalanced <DOCUMENT> delimiter"
    )


def test_scan_unbalanced_closes_are_detected() -> None:
    """A close before an open, or a trailing close, is a structural failure."""
    assert (
        _check_document_delimiters(b"<DOCUMENT>text</DOCUMENT></DOCUMENT>")
        == "unbalanced </DOCUMENT> delimiter"
    )
    assert (
        _check_document_delimiters(b"</DOCUMENT>") == "unbalanced </DOCUMENT> delimiter"
    )


def test_scan_empty_is_valid() -> None:
    """No delimiters at all is valid, producing no scan error."""
    assert _check_document_delimiters(b"") is None


def test_slice_body_uses_text_and_strips_wrapping() -> None:
    """A TEXT wrapper is stripped of its own \\r\n; blocks without TEXT pass through."""
    with_text = b"<TEXT>\nBODY\n</TEXT>"
    assert _slice_body(with_text, 0, len(with_text)) == b"BODY"
    without = b"<TYPE>10-K\n<SEQUENCE>1\n<FILENAME>a.htm\n"
    assert _slice_body(without, 0, len(without)) == without.strip()


def test_slice_body_handles_plain_html_block() -> None:
    """A block whose body is literal markup uses the whole block."""
    block = b"<HTML><BODY>Hello</BODY></HTML>"
    assert _slice_body(block, 0, len(block)) == block
