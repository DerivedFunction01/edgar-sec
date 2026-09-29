"""Unit and contract tests for edgar_sec.engine.document.unpacker."""

from __future__ import annotations

from edgar_sec.engine.document.unpacker import (
    find_sub_document,
    resolve_target_sub_document,
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


def test_find_sub_document() -> None:
    docs = unpack_sgml_submission(SAMPLE_SGML)

    match_type = find_sub_document(docs, target_types=["10-K"])
    assert match_type is not None
    assert match_type.doc_type == "10-K"

    match_file = find_sub_document(docs, filename_patterns=["ex21"])
    assert match_file is not None
    assert match_file.filename == "ex21.txt"

    assert find_sub_document(docs, target_types=["8-K"]) is None


def test_resolve_target_sub_document() -> None:
    docs = unpack_sgml_submission(SAMPLE_SGML)

    # Resolution by target type
    res1 = resolve_target_sub_document(docs, target_types=["10-K"])
    assert res1 is not None
    assert res1.doc_type == "10-K"

    # Resolution by primary filename
    res2 = resolve_target_sub_document(docs, primary_filename="form10k.htm")
    assert res2 is not None
    assert res2.filename == "form10k.htm"

    # Fallback to sequence 1
    res3 = resolve_target_sub_document(docs, fallback_to_sequence_one=True)
    assert res3 is not None
    assert res3.sequence == 1
