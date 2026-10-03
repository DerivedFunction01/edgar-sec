"""Unit and contract tests for edgar_sec.engine.document.unpacking.unpacker.

Re-lands the suite deleted in commit `079010e` for a module that still has two
production callers (`pipelines/document_storage/fetching.py` and
`delegation.py`), and extends it to the extraction and malformed-input paths
the pipeline reaches but the deleted file never covered.
"""

from __future__ import annotations

from edgar_sec.engine.document.unpacking.unpacker import (
    SgmlSubDocument,
    extract_target_sub_document,
    find_sub_document,
    has_sgml_documents,
    resolve_target_sub_document,
    strip_pem_envelope,
    unpack_sgml_submission,
)

SAMPLE_SGML = """<SEC-DOCUMENT>0000000000-00-000000.txt : 20240101
<SEC-HEADER>0000000000-00-000000.hdr.sgml : 20240101
ACCESSION NUMBER: 0000000000-00-000000
</SEC-HEADER>
<DOCUMENT>
<TYPE>10-K
<SEQUENCE>1
<FILENAME>form10k.htm
<DESCRIPTION>ANNUAL REPORT
<TEXT>
<html><body><h1>Annual Report</h1><p>Prose here.</p></body></html>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-21
<SEQUENCE>2
<FILENAME>ex21.txt
<DESCRIPTION>SUBSIDIARIES
<TEXT>
Subsidiary list.
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>GRAPHIC
<SEQUENCE>3
<FILENAME>image.jpg
<TEXT>
binarygarbage
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>
"""

PEM = (
    b"-----BEGIN PRIVACY-ENHANCED MESSAGE-----\n"
    b"Proc-Type: 4,ENCRYPTED\n\n"
    b"payload bytes\n"
    b"-----END PRIVACY-ENHANCED MESSAGE-----"
)


def test_unpack_sgml_submission() -> None:
    docs = unpack_sgml_submission(SAMPLE_SGML)
    assert len(docs) == 3

    d1 = docs[0]
    assert d1.doc_type == "10-K"
    assert d1.sequence == 1
    assert d1.filename == "form10k.htm"
    assert d1.description == "ANNUAL REPORT"
    assert d1.is_html is True
    assert b"Annual Report" in d1.raw_payload

    d2 = docs[1]
    assert d2.doc_type == "EX-21"
    assert d2.sequence == 2
    assert d2.filename == "ex21.txt"
    assert d2.is_html is False
    assert b"Subsidiary list." in d2.raw_payload

    d3 = docs[2]
    assert d3.doc_type == "GRAPHIC"
    assert d3.sequence == 3
    assert d3.filename == "image.jpg"


def test_unpack_sgml_submission_bytes() -> None:
    docs = unpack_sgml_submission(SAMPLE_SGML.encode("utf-8"))
    assert len(docs) == 3
    assert docs[0].doc_type == "10-K"


def test_unpack_never_raises_on_empty_or_bare_input() -> None:
    assert unpack_sgml_submission("") == []
    assert unpack_sgml_submission(b"") == []
    assert unpack_sgml_submission("no envelope here") == []
    assert has_sgml_documents(b"") is False
    assert has_sgml_documents(b"plain text") is False
    assert has_sgml_documents(SAMPLE_SGML.encode()) is True


def test_find_sub_document() -> None:
    docs = unpack_sgml_submission(SAMPLE_SGML)

    match_type = find_sub_document(docs, target_types=["10-K"])
    assert match_type is not None
    assert match_type.doc_type == "10-K"

    match_file = find_sub_document(docs, filename_patterns=["ex21"])
    assert match_file is not None
    assert match_file.filename == "ex21.txt"

    assert find_sub_document(docs, target_types=["8-K"]) is None


def test_find_sub_document_on_empty_list() -> None:
    assert find_sub_document([], target_types=["10-K"]) is None


def test_resolve_target_sub_document() -> None:
    docs = unpack_sgml_submission(SAMPLE_SGML)

    by_type = resolve_target_sub_document(docs, target_types=["10-K"])
    assert by_type is not None
    assert by_type.doc_type == "10-K"

    by_filename = resolve_target_sub_document(docs, primary_filename="form10k.htm")
    assert by_filename is not None
    assert by_filename.filename == "form10k.htm"

    by_sequence = resolve_target_sub_document(docs, fallback_to_sequence_one=True)
    assert by_sequence is not None
    assert by_sequence.sequence == 1


def test_resolve_target_sub_document_falls_back_to_the_first_text_document() -> None:
    """Tier 4: an unmatched target type still resolves to the first text document.

    Returning `None` here would abort acquisition of any filing whose `<TYPE>`
    the caller did not enumerate, so this fallback is the important case.
    """
    docs = unpack_sgml_submission(SAMPLE_SGML)
    fallback = resolve_target_sub_document(docs, target_types=["40-F"])
    assert fallback is not None
    assert fallback.doc_type == "10-K"

    assert resolve_target_sub_document([]) is None


def test_resolve_target_sub_document_skips_binary_documents_in_the_fallback() -> None:
    raw = (
        b"<DOCUMENT><TYPE>GRAPHIC<SEQUENCE>1<FILENAME>a.jpg<TEXT>bin</TEXT></DOCUMENT>"
        b"<DOCUMENT><TYPE>10-K<SEQUENCE>2<FILENAME>b.htm<TEXT>real</TEXT></DOCUMENT>"
    )
    payload = extract_target_sub_document(raw, target_types=("40-F",))
    assert payload == b"real"


def test_extract_target_sub_document_slices_only_the_winner() -> None:
    raw = SAMPLE_SGML.encode("utf-8")
    payload = extract_target_sub_document(raw, target_types=["10-K"])
    assert payload is not None
    assert b"Annual Report" in payload
    assert b"Subsidiary list." not in payload
    assert b"<DOCUMENT>" not in payload


def test_extract_target_sub_document_returns_none_without_a_document() -> None:
    assert extract_target_sub_document(b"") is None
    assert extract_target_sub_document(b"no envelope at all") is None


def test_extract_target_sub_document_skips_binary_first_document() -> None:
    raw = (
        b"<DOCUMENT><TYPE>GRAPHIC<SEQUENCE>1<FILENAME>a.jpg<TEXT>bin</TEXT></DOCUMENT>"
        b"<DOCUMENT><TYPE>10-K<SEQUENCE>2<FILENAME>b.htm<TEXT>real</TEXT></DOCUMENT>"
    )
    payload = extract_target_sub_document(raw, target_types=("10-K",))
    assert payload == b"real"


def test_sgml_sub_document_is_frozen() -> None:
    doc = SgmlSubDocument(
        doc_type="10-K",
        sequence=1,
        filename="a.htm",
        description=None,
        raw_payload=b"x",
        is_html=True,
    )
    assert doc.description is None
    try:
        doc.doc_type = "8-K"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("SgmlSubDocument must be frozen")


def test_strip_pem_envelope() -> None:
    stripped = strip_pem_envelope(PEM)
    assert b"BEGIN PRIVACY-ENHANCED" not in stripped
    assert b"payload bytes" in stripped


def test_strip_pem_envelope_passes_through_unwrapped_payload() -> None:
    assert strip_pem_envelope(b"plain") == b"plain"
    assert strip_pem_envelope(b"") == b""


def test_latin1_round_trip_preserves_payload_bytes() -> None:
    raw = SAMPLE_SGML.encode("latin-1")
    docs = unpack_sgml_submission(raw)
    assert docs[0].raw_payload.decode("latin-1").encode("latin-1") == (
        docs[0].raw_payload
    )
