from defs.sec_documents.sgml import (
    extract_sub_document,
    extract_target_sub_document,
    has_sgml_documents,
    resolve_target_sub_document,
    unpack_sgml_submission,
)

SAMPLE_SGML = b"""<SUBMISSION>
<ACCESSION-NUMBER>0000000000-00-000001
<TYPE>10-K
<DOCUMENT>
<TYPE>10-K
<SEQUENCE>1
<FILENAME>primary.htm
<DESCRIPTION>FORM 10-K
<TEXT>
<html><body>
<h1>Annual Report</h1>
<p>Items 1, 7, and 8 incorporated by reference to Exhibit 13.</p>
</body></html>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>GRAPHIC
<SEQUENCE>2
<FILENAME>logo.jpg
<DESCRIPTION>Company Logo
<TEXT>
[BINARY JUNK]
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-13
<SEQUENCE>3
<FILENAME>ex13.htm
<DESCRIPTION>ANNUAL REPORT TO SHAREHOLDERS
<TEXT>
<html><body>
<h2>Item 1. Business</h2>
<p>Our core business operations described in detail.</p>
<h2>Item 7. MD&A</h2>
<p>Financial review and results.</p>
</body></html>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-21
<SEQUENCE>4
<FILENAME>ex21.txt
<DESCRIPTION>SUBSIDIARIES
<TEXT>
Subsidiary A, Delaware.
</TEXT>
</DOCUMENT>
</SUBMISSION>
"""


def test_unpack_sgml_submission_empty():
    assert unpack_sgml_submission(b"") == []


def test_unpack_sgml_submission_multiple():
    docs = unpack_sgml_submission(SAMPLE_SGML)
    assert len(docs) == 4

    # Document 1: 10-K
    doc0 = docs[0]
    assert doc0.doc_type == "10-K"
    assert doc0.sequence == 1
    assert doc0.filename == "primary.htm"
    assert doc0.description == "FORM 10-K"
    assert b"Annual Report" in doc0.raw_payload
    assert doc0.is_html is True

    # Document 2: GRAPHIC
    doc1 = docs[1]
    assert doc1.doc_type == "GRAPHIC"
    assert doc1.sequence == 2
    assert doc1.filename == "logo.jpg"
    assert doc1.is_html is False

    # Document 3: EX-13
    doc2 = docs[2]
    assert doc2.doc_type == "EX-13"
    assert doc2.sequence == 3
    assert doc2.filename == "ex13.htm"
    assert b"Item 1. Business" in doc2.raw_payload
    assert doc2.is_html is True

    # Document 4: EX-21
    doc3 = docs[3]
    assert doc3.doc_type == "EX-21"
    assert doc3.sequence == 4
    assert doc3.filename == "ex21.txt"
    assert b"Subsidiary A" in doc3.raw_payload
    assert doc3.is_html is False


def test_extract_sub_document_by_type():
    exhibit = extract_sub_document(SAMPLE_SGML, target_types=("EX-13", "EXHIBIT 13"))
    assert exhibit is not None
    assert exhibit.doc_type == "EX-13"
    assert exhibit.filename == "ex13.htm"
    assert b"Item 1. Business" in exhibit.raw_payload


def test_extract_sub_document_by_filename():
    sgml_sample = b"""<DOCUMENT>
<TYPE>OTHER
<SEQUENCE>2
<FILENAME>exhibit99_financials.htm
<DESCRIPTION>Financials
<TEXT>
<html><body>Substantive Report</body></html>
</TEXT>
</DOCUMENT>
"""
    exhibit = extract_sub_document(
        sgml_sample,
        filename_patterns=("exhibit99", "ex99"),
    )
    assert exhibit is not None
    assert exhibit.filename == "exhibit99_financials.htm"
    assert b"Substantive Report" in exhibit.raw_payload


def test_extract_sub_document_missing():
    sgml_sample = b"""<DOCUMENT>
<TYPE>10-K
<FILENAME>10k.htm
<TEXT>Sample</TEXT>
</DOCUMENT>
"""
    exhibit = extract_sub_document(sgml_sample, target_types=("EX-99", "EX-13"))
    assert exhibit is None


def test_resolve_target_sub_document_across_multiple_forms():
    # 1. 10-K exact form match
    docs = unpack_sgml_submission(SAMPLE_SGML)
    res_10k = resolve_target_sub_document(docs, target_types=("10-K", "10-K/A"))
    assert res_10k is not None
    assert res_10k.doc_type == "10-K"
    assert res_10k.filename == "primary.htm"

    # 2. 20-F sample
    sgml_20f = b"""<DOCUMENT>
<TYPE>20-F
<SEQUENCE>1
<FILENAME>f20f2023.htm
<TEXT>Foreign Issuer Annual Report</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>GRAPHIC
<FILENAME>chart.png
<TEXT>[PNG]</TEXT>
</DOCUMENT>
"""
    docs_20f = unpack_sgml_submission(sgml_20f)
    res_20f = resolve_target_sub_document(docs_20f, target_types=("20-F", "20-F/A"))
    assert res_20f is not None
    assert res_20f.doc_type == "20-F"
    assert b"Foreign Issuer" in res_20f.raw_payload

    # 3. 10-Q sample
    sgml_10q = b"""<DOCUMENT>
<TYPE>10-Q/A
<SEQUENCE>1
<FILENAME>q2_amend.htm
<TEXT>Quarterly Report Amendment</TEXT>
</DOCUMENT>
"""
    docs_10q = unpack_sgml_submission(sgml_10q)
    res_10q = resolve_target_sub_document(docs_10q, target_types=("10-Q", "10-Q/A"))
    assert res_10q is not None
    assert res_10q.doc_type == "10-Q/A"

    # 4. 8-K sample
    sgml_8k = b"""<DOCUMENT>
<TYPE>8-K
<SEQUENCE>1
<FILENAME>currentevent.htm
<TEXT>Current Report Item 1.01</TEXT>
</DOCUMENT>
"""
    docs_8k = unpack_sgml_submission(sgml_8k)
    res_8k = resolve_target_sub_document(docs_8k, target_types=("8-K", "8-K/A"))
    assert res_8k is not None
    assert res_8k.doc_type == "8-K"

    # 5. Filename match when TYPE is generic or irregular
    sgml_generic = b"""<DOCUMENT>
<TYPE>REPORT
<SEQUENCE>2
<FILENAME>my_special_filing.htm
<TEXT>Special Content</TEXT>
</DOCUMENT>
"""
    docs_generic = unpack_sgml_submission(sgml_generic)
    res_fn = resolve_target_sub_document(
        docs_generic, primary_filename="path/to/my_special_filing.htm"
    )
    assert res_fn is not None
    assert res_fn.filename == "my_special_filing.htm"

    # 6. Sequence 1 fallback
    sgml_seq1 = b"""<DOCUMENT>
<TYPE>ATTACHMENT
<SEQUENCE>1
<FILENAME>main_content.txt
<TEXT>Sequence 1 Main Filing</TEXT>
</DOCUMENT>
"""
    docs_seq1 = unpack_sgml_submission(sgml_seq1)
    res_seq1 = resolve_target_sub_document(docs_seq1)
    assert res_seq1 is not None
    assert res_seq1.sequence == 1
    assert b"Sequence 1" in res_seq1.raw_payload

    # 7. Delegated Exhibit (EX-13) via target_types
    sgml_exhibit = b"""<DOCUMENT>
<TYPE>GRAPHIC
<SEQUENCE>1
<FILENAME>cover.jpg
<TEXT>[COVER]</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-13
<SEQUENCE>2
<FILENAME>annual_report.htm
<TEXT>Annual Report to Shareholders</TEXT>
</DOCUMENT>
"""
    docs_ex = unpack_sgml_submission(sgml_exhibit)
    res_ex = resolve_target_sub_document(docs_ex, target_types=("10-K", "EX-13"))
    assert res_ex is not None
    assert res_ex.doc_type == "EX-13"
    assert b"Annual Report to Shareholders" in res_ex.raw_payload


# ---------------------------------------------------------------------------
# Selective target extraction: byte equivalence with unpack + resolve
# ---------------------------------------------------------------------------


def _selective_equivalent(raw: bytes, **kwargs) -> bytes | None:
    docs = unpack_sgml_submission(raw)
    winner = resolve_target_sub_document(docs, **kwargs)
    expected = winner.raw_payload if winner is not None else None
    actual = extract_target_sub_document(raw, **kwargs)
    assert actual == expected
    return actual


def test_extract_target_sub_document_matches_unpack_resolve_all_tiers():
    # Tier 1: by type
    assert (
        _selective_equivalent(SAMPLE_SGML, target_types=("10-K", "10-K/A"))
        == b"<html><body>\n<h1>Annual Report</h1>\n<p>Items 1, 7, and 8 incorporated by reference to Exhibit 13.</p>\n</body></html>"
    )
    # Tier 1 skips graphics by extension
    _selective_equivalent(SAMPLE_SGML, target_types=("EX-13",))
    # Tier 2: by primary filename
    _selective_equivalent(
        SAMPLE_SGML, primary_filename="dir/ex21.txt", fallback_to_sequence_one=False
    )
    # Tier 3: sequence-1 fallback skips GRAPHIC sequences
    sgml_graphic_first = b"""<DOCUMENT>
<TYPE>GRAPHIC
<SEQUENCE>1
<FILENAME>cover.jpg
<TEXT>[COVER]</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>ATTACHMENT
<SEQUENCE>1
<FILENAME>main.txt
<TEXT>Main content</TEXT>
</DOCUMENT>
"""
    payload = _selective_equivalent(sgml_graphic_first)
    assert payload == b"Main content"
    # Tier 4: first non-graphic fallback
    sgml_generic = b"""<DOCUMENT>
<TYPE>ZIP
<SEQUENCE>1
<FILENAME>bundle.zip
<TEXT>[ZIP]</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>NOTICE
<SEQUENCE>2
<FILENAME>notice.txt
<TEXT>Notice body</TEXT>
</DOCUMENT>
"""
    assert _selective_equivalent(sgml_generic) == b"Notice body"


def test_extract_target_sub_document_no_blocks_returns_none():
    assert not has_sgml_documents(b"plain document body without sgml tags")
    assert extract_target_sub_document(b"plain document") is None
    assert has_sgml_documents(b"") is False
    assert extract_target_sub_document(b"") is None


def test_extract_target_sub_document_missing_text_tag_fallback():
    raw = b"""<DOCUMENT>
<TYPE>10-K
<SEQUENCE>1
<FILENAME>10k.htm
</DOCUMENT>
"""
    assert _selective_equivalent(raw) is not None


def test_extract_target_sub_document_stub_filename_excluded_from_tier2():
    raw = b"""<DOCUMENT>
<TYPE>10-K
<SEQUENCE>1
<FILENAME>real10k.htm
<TEXT>Real filing</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>10-K
<SEQUENCE>2
<FILENAME>0001.htm
<TEXT>Stub page</TEXT>
</DOCUMENT>
"""
    assert _selective_equivalent(raw, primary_filename="0001.htm") == b"Real filing"


def test_extract_target_sub_document_crlf_and_multibyte_payloads():
    raw = (
        b"<DOCUMENT>\r\n<TYPE>10-K\r\n<SEQUENCE>1\r\n<FILENAME>a.htm\r\n"
        b"<TEXT>\r\ncaf\xe9 line\r\nsecond line\r\n</TEXT>\r\n</DOCUMENT>\r\n"
    )
    payload = _selective_equivalent(raw)
    assert payload == b"caf\xe9 line\r\nsecond line"
