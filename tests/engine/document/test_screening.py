"""Unit tests for candidate document screening.

Verifies SGML type screening, filename exhibit detection, and normalized text evaluation.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.screening import screen_candidate_document


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
