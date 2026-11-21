"""Pins for the tag local-name home (Wave 2B).
The namespace strip lives in ``engine.forms.common.fields.extraction``;
the filing-summary parser binds it.
"""

from __future__ import annotations

from edgar_sec.engine.filing_summary import parser
from edgar_sec.engine.forms.common.fields.extraction import local_name


def test_binding_is_the_extraction_home() -> None:
    assert parser.local_name is local_name


def test_local_name_verdicts() -> None:
    assert local_name("{http://www.sec.gov/edgar}File") == "File"
    assert local_name("File") == "File"
    assert local_name("{}") == ""
    assert local_name("{a}b}c") == "c"
