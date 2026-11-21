"""Shared payload constants for the normalize suites."""

from __future__ import annotations


_HARD_WRAPPED = (
    b"The Registrant hereby reports the following matters in accordance with\n"
    b"the requirements of the Securities Exchange Act of 1934, as amended.\n"
    b"This paragraph continues across several hard-wrapped source lines\n"
    b"and is unwrapped into one flowing sentence.\n"
)


_PAPER_STUB = (
    b"<SEC-HEADER>\n"
    b"<DOCUMENT>\n"
    b"<TYPE>19B-4E\n"
    b"<SEQUENCE>1\n"
    b"<FILENAME>9999999997-25-001505.paper\n"
    b"<DESCRIPTION>AUTO-GENERATED PAPER DOCUMENT\n"
    b"<TEXT>\n"
    b"This document was generated as part of a paper submission.\n"
    b"Please reference the Document Control Number 25000522 for access to "
    b"the original document.\n"
    b"</TEXT>\n"
    b"</DOCUMENT>\n"
    b"</SEC-DOCUMENT>\n"
)


_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"


_TAGGED_TABLE_TOC = (
    "FORM 10-K\n"
    "ACME CORPORATION\n"
    "TABLE OF CONTENTS\n"
    "<TABLE>\n"
    "PART I ........................................ 1\n"
    "ITEM 1. BUSINESS ............................. 1\n"
    "ITEM 1A. RISK FACTORS ......................... 8\n"
    "</TABLE>\n"
    "PART I\n"
    "ITEM 1. BUSINESS\n"
    "Acme provides widgets to customers nationwide.\n"
)
