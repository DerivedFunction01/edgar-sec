"""Route classification: a slash outranks the suffix."""

from __future__ import annotations

import pytest

from edgar_sec.domain.document.route import (
    DEFAULT_MIME,
    MARKUP_SUFFIXES,
    DocumentRoute,
    archive_root_candidate,
    content_route,
    document_route,
    is_markup_document_path,
    is_rendered_document_path,
    mime_type_for_suffix,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # A slash is an XSL directory for a URL, never for an SGML filename.
        ("xslF345X02/edgar.xml", DocumentRoute.XML),
        ("xsl144X01/primary_doc.xml", DocumentRoute.XML),
        ("edgar.xml", DocumentRoute.XML),
        ("acme-10k.htm", DocumentRoute.MARKUP),
        ("note.txt", DocumentRoute.TEXT),
        ("9999999997-25-001505.paper", DocumentRoute.PAPER),
        ("chart.pdf", DocumentRoute.BINARY),
        ("weird.frm", DocumentRoute.UNKNOWN),
        ("", DocumentRoute.UNKNOWN),
        (None, DocumentRoute.UNKNOWN),
    ],
)
def test_content_route_ignores_any_directory(
    path: str | None, expected: DocumentRoute
) -> None:
    assert content_route(path) is expected


def test_content_route_disagrees_with_document_route_for_a_rendered_path() -> None:
    """The two classifiers answer different questions, so a slash separates them."""
    path = "xslF345X02/edgar.xml"
    assert document_route(path) is DocumentRoute.RENDERED
    assert content_route(path) is DocumentRoute.XML


def test_content_route_agrees_with_document_route_for_a_flat_path() -> None:
    assert content_route("acme-10k.htm") is document_route("acme-10k.htm")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("xslF345X02/edgar.xml", DocumentRoute.RENDERED),
        ("xsl144X01/primary_doc.xml", DocumentRoute.RENDERED),
        ("xslEFFECTX01/effect.xml", DocumentRoute.RENDERED),
        ("edgar.htm", DocumentRoute.MARKUP),
        ("report.html", DocumentRoute.MARKUP),
        ("inline.xhtml", DocumentRoute.MARKUP),
        ("form10k.txt", DocumentRoute.TEXT),
        ("9999999997-25-001505.paper", DocumentRoute.PAPER),
        ("primary_doc.xml", DocumentRoute.XML),
        ("F29J100226.pdf", DocumentRoute.BINARY),
        ("logo.gif", DocumentRoute.BINARY),
        ("scan.jpg", DocumentRoute.BINARY),
        ("weird.frm", DocumentRoute.UNKNOWN),
        ("", DocumentRoute.UNKNOWN),
        (None, DocumentRoute.UNKNOWN),
    ],
)
def test_route_selected_by_path_shape_and_suffix(
    path: str | None, expected: DocumentRoute
) -> None:
    assert document_route(path) is expected


def test_slash_outranks_suffix() -> None:
    """An XSL rendering is HTML whatever it is named."""
    assert document_route("xslF345X02/edgar.xml") is DocumentRoute.RENDERED
    assert document_route("edgar.xml") is DocumentRoute.XML


def test_suffix_matching_is_case_insensitive() -> None:
    assert document_route("EDGAR.HTM") is DocumentRoute.MARKUP
    assert document_route("Doc.PAPER") is DocumentRoute.PAPER


def test_archive_root_candidate_only_for_rendered() -> None:
    assert archive_root_candidate("xslF345X02/edgar.xml") == "edgar.xml"
    assert archive_root_candidate("edgar.htm") is None
    assert archive_root_candidate(None) is None


def test_is_rendered_matches_route() -> None:
    assert is_rendered_document_path("xsl144X01/x.xml") is True
    assert is_rendered_document_path("x.xml") is False


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("edgar.htm", "text/html"),
        ("report.html", "text/html"),
        ("inline.xhtml", "text/html"),
        ("form10k.txt", "text/plain"),
        ("primary_doc.xml", "text/xml"),
        ("F29J100226.pdf", "application/pdf"),
        ("logo.gif", "image/gif"),
        ("scan.JPG", "image/jpeg"),
        ("weird.frm", DEFAULT_MIME),
        ("noextension", DEFAULT_MIME),
        ("", DEFAULT_MIME),
        (None, DEFAULT_MIME),
    ],
)
def test_mime_type_follows_the_suffix(path: str | None, expected: str) -> None:
    assert mime_type_for_suffix(path) == expected


def test_rendered_path_is_named_by_its_basename_suffix() -> None:
    """A rendering is served under a directory but named by its own extension."""
    assert mime_type_for_suffix("xslF345X02/edgar.xml") == "text/xml"
    assert mime_type_for_suffix("xslF345X02/edgar.htm") == "text/html"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("edgar.htm", True),
        ("report.html", True),
        ("inline.xhtml", True),
        ("EDGAR.HTM", True),
        # A rendering is served as HTML whatever its basename is named, so a
        # suffix-only test would call this one non-markup.
        ("xslF345X02/edgar.xml", True),
        ("xsl144X01/primary_doc.xml", True),
        ("form10k.txt", False),
        ("primary_doc.xml", False),
        ("chart.pdf", False),
        ("9999999997-25-001505.paper", False),
        ("weird.frm", False),
        (None, False),
    ],
)
def test_markup_predicate_covers_renderings(path: str | None, expected: bool) -> None:
    assert is_markup_document_path(path) is expected


def test_markup_predicate_agrees_with_the_suffix_set() -> None:
    """One vocabulary, so a caller cannot classify markup two different ways."""
    for suffix in MARKUP_SUFFIXES:
        assert is_markup_document_path(f"doc{suffix}") is True
