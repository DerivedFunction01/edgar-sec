"""Unit tests for candidate document screening.

Verifies SGML type screening, filename exhibit detection, and normalized text evaluation.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.screening import (
    screen_candidate_document,
    screen_specialized_xml_source,
)


def test_screen_observed_sgml_type_match() -> None:
    """Observed SGML matching form produces form_match."""
    res = screen_candidate_document("10-K", observed_sgml_type="10-K")
    assert res.screen_result == "form_match"
    assert not res.is_inversion
    assert res.screen_kind == "sgml_type"


def test_screen_observed_sgml_type_mismatch() -> None:
    """Observed SGML exhibit or competing form produces type_mismatch."""
    res = screen_candidate_document("10-K", observed_sgml_type="EX-10.1")
    assert res.screen_result == "type_mismatch"
    assert res.is_inversion
    assert res.screen_kind == "sgml_type"


def test_screen_observed_sgml_type_none() -> None:
    """Observed SGML None produces unverifiable under sgml_type."""
    res = screen_candidate_document("10-K", observed_sgml_type=None)
    assert res.screen_result == "unverifiable"
    assert not res.is_inversion
    assert res.screen_kind == "sgml_type"


def test_screen_raw_content_sgml_tags() -> None:
    """Raw content with SGML TYPE tags evaluates correctly."""
    ex_bytes = b"<DOCUMENT>\n<TYPE>EX-10.1\n<TEXT>\n"
    assert screen_candidate_document("10-K", raw_content=ex_bytes).is_inversion

    match_bytes = b"<DOCUMENT>\n<TYPE>10-K\n<TEXT>\n"
    screen = screen_candidate_document("10-K", raw_content=match_bytes)
    assert screen.screen_result == "form_match"
    assert not screen.is_inversion

    competing_bytes = b"<DOCUMENT>\n<TYPE>8-K\n<TEXT>\n"
    screen_comp = screen_candidate_document("10-K", raw_content=competing_bytes)
    assert screen_comp.screen_result == "type_mismatch"
    assert screen_comp.is_inversion


@pytest.mark.parametrize(
    ("expected_form", "observed_type"),
    [("4", "4/A"), ("4/A", "4")],
)
def test_screen_sgml_identity_uses_form_family(
    expected_form: str, observed_type: str
) -> None:
    """Amendment aliases match at family level on both SGML entry paths."""
    observed = screen_candidate_document(
        expected_form, observed_sgml_type=observed_type
    )
    raw = screen_candidate_document(
        expected_form,
        raw_content=f"<DOCUMENT>\n<TYPE>{observed_type}\n<TEXT>\n".encode(),
    )

    assert observed.screen_result == raw.screen_result == "form_match"
    assert not observed.is_inversion and not raw.is_inversion
    assert observed.observed_body_type == raw.observed_body_type == observed_type


@pytest.mark.parametrize(
    ("expected_form", "observed_type"),
    [("4", "4/A"), ("4/A", "4")],
)
def test_screen_sgml_amendment_flag_mismatch_reason(
    expected_form: str, observed_type: str
) -> None:
    """A flag-only difference stays a match but surfaces its own reason."""
    observed = screen_candidate_document(
        expected_form, observed_sgml_type=observed_type
    )
    raw = screen_candidate_document(
        expected_form,
        raw_content=f"<DOCUMENT>\n<TYPE>{observed_type}\n<TEXT>\n".encode(),
    )

    for screen in (observed, raw):
        assert screen.screen_result == "form_match"
        assert not screen.is_inversion
        assert screen.reason == "sgml_type_amendment_flag_mismatch"
        assert screen.observed_body_type == observed_type


@pytest.mark.parametrize(
    ("expected_form", "observed_type"),
    [("4", "4"), ("4/A", "4/A"), ("10-K", "10-K")],
)
def test_screen_sgml_same_flag_keeps_match_reason(
    expected_form: str, observed_type: str
) -> None:
    screen = screen_candidate_document(expected_form, observed_sgml_type=observed_type)

    assert screen.screen_result == "form_match"
    assert screen.reason == "sgml_type_match"


def test_screen_raw_content_sgml_competing_family() -> None:
    screen = screen_candidate_document(
        "4", raw_content=b"<DOCUMENT>\n<TYPE>8-K\n<TEXT>\n"
    )

    assert screen.screen_result == "type_mismatch"
    assert screen.is_inversion
    assert screen.observed_body_type == "8-K"


def test_screen_filename_exhibit() -> None:
    """Exhibit filenames produce inversion type_mismatch."""
    assert screen_candidate_document("10-K", filename="ex-101.htm").is_inversion
    assert screen_candidate_document("10-K", filename="exhibit99.htm").is_inversion
    assert not screen_candidate_document("10-K", filename="form10k.htm").is_inversion


def test_screen_raw_html_bypasses_screening() -> None:
    """Raw HTML without normalized text produces unverifiable."""
    html_raw = b"<html><body><div>Some content</div></body></html>"
    res = screen_candidate_document("10-K", filename="form.htm", raw_content=html_raw)
    assert res.screen_result == "unverifiable"
    assert not res.is_inversion


def test_screen_normalized_text_exhibit_probe() -> None:
    """Normalized text with opening exhibit header detects inversion."""
    norm_text = "EXHIBIT 10.1\nCREDIT AGREEMENT\nDated as of June 1, 2023\n"
    res = screen_candidate_document(
        "10-K", filename="doc.htm", normalized_text=norm_text
    )
    assert res.screen_result == "type_mismatch"
    assert res.is_inversion
    assert res.screen_kind == "exhibit_header"


def test_screen_normalized_text_matching_form_title() -> None:
    """Normalized text matching canonical form title produces form_match."""
    norm_text = (
        "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\nFORM 10-K\nANNUAL REPORT\n"
    )
    res = screen_candidate_document(
        "10-K", filename="doc.htm", normalized_text=norm_text
    )
    assert res.screen_result == "form_match"
    assert not res.is_inversion
    assert res.screen_kind == "html_cover"


def test_screen_normalized_text_competing_form_title() -> None:
    """Normalized text with competing form title produces type_mismatch."""
    norm_text = (
        "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\nFORM 8-K\nCURRENT REPORT\n"
    )
    res = screen_candidate_document(
        "10-K", filename="doc.htm", normalized_text=norm_text
    )
    assert res.screen_result == "type_mismatch"
    assert res.is_inversion
    assert res.screen_kind == "html_cover"


def test_specialized_xml_screen_marks_prose_unverifiable_not_inversion() -> None:
    """Marker-missing prose has no type evidence either way: unverifiable."""
    prose = b"<html><body><h1>Exhibit 99.1</h1><p>Acme announced a new partnership.</p></body></html>"
    screen = screen_specialized_xml_source("4", prose)
    assert not screen.is_inversion
    assert screen.screen_result == "unverifiable"
    assert screen.reason == "form_structure_markers_missing"


def test_specialized_xml_screen_unverifiable_without_identity_marker() -> None:
    prose = (
        b"<html><body>Issuer Acme. See Table I in the attached release.</body></html>"
    )
    screen = screen_specialized_xml_source("4", prose)
    assert not screen.is_inversion
    assert screen.screen_result == "unverifiable"


def test_specialized_xml_screen_accepts_reporting_person_vocabulary() -> None:
    """Paper forms name the Reporting Person, not Reporting Owner."""
    paper_txt = (
        b"<DOCUMENT>\n<TYPE>4\n<SEQUENCE>1\n<FILENAME>0001.txt\n<TEXT>\n"
        b"FORM 4\n1. Name and Address of Reporting Person\n"
        b"2. Issuer Name and Ticker or Trading Symbol\n"
        b"6. Relationship of Reporting Person(s) to Issuer\n"
        b"TABLE I -- Non-Derivative Securities Acquired, Disposed of\n"
        b"</TEXT>\n</DOCUMENT>\n"
    )
    screen = screen_specialized_xml_source("4", paper_txt)
    assert screen.screen_result == "form_match"
    assert not screen.is_inversion

    paper_html = (
        b"<html><body><h1>FORM 3</h1>"
        b"<p>1. Name and Address of Reporting Person: Smith, Jane</p>"
        b"<p>2. Issuer Name: Acme Corporation</p>"
        b"<p>Relationship of Reporting Person to Issuer: Director</p>"
        b"<p>Table I - Non-Derivative Securities</p></body></html>"
    )
    screen = screen_specialized_xml_source("3", paper_html)
    assert screen.screen_result == "form_match"
    assert not screen.is_inversion


def test_screen_exhibit_in_primary_slot_is_inversion() -> None:
    """An exhibit type in the primary slot is a type-identity mismatch."""
    body = b"<DOCUMENT>\n<TYPE>EX-99.1\n<TEXT>\nPress release.\n"
    screen = screen_candidate_document("4", filename="0001.txt", raw_content=body)
    assert screen.is_inversion
    assert screen.screen_result == "type_mismatch"


def test_specialized_xml_screen_accepts_ownership_without_derivative_table() -> None:
    ownership = b"""<html><body>
    <h1>FORM 4</h1><p>Issuer Acme Corporation</p>
    <p>Reporting Owner: Jane Smith</p>
    <p>Relationship of Reporting Person: Director</p>
    <p>Table I - Non-Derivative Securities</p>
    </body></html>"""
    screen = screen_specialized_xml_source("4", ownership)
    assert screen.screen_result == "form_match"
    assert not screen.is_inversion


@pytest.mark.parametrize(
    ("form", "body"),
    [
        (
            "144",
            b"Form 144 Notice of Proposed Sale. Issuer Acme. Securities to be sold.",
        ),
        (
            "13D",
            b"Schedule 13D. Reporting Person Jane Smith. Issuer Acme. Item 1.",
        ),
        (
            "13G",
            b"Schedule 13G. Reporting Person Jane Smith. Issuer Acme. Item 1.",
        ),
    ],
)
def test_specialized_xml_screen_accepts_registered_family_signals(
    form: str, body: bytes
) -> None:
    screen = screen_specialized_xml_source(form, body)
    assert screen.screen_result == "form_match"
