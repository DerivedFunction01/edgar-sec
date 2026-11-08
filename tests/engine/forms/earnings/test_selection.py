"""Tests for filename-family exhibit selection."""

from edgar_sec.engine.forms.earnings.selection import (
    classify_kind,
    match_exhibit_filename,
    select_exhibit_candidates,
)


def test_filename_families_match() -> None:
    """Each recorded filename family resolves to its exhibit number."""
    assert match_exhibit_filename("ex99-1.htm") == (1, "modern")
    assert match_exhibit_filename("ex-99.2.htm") == (2, "modern")
    assert match_exhibit_filename("exhibit993.htm") == (3, "exhibit")
    assert match_exhibit_filename("exhibit_991.htm") == (1, "exhibit")
    assert match_exhibit_filename("exh_991.htm") == (1, "short")
    assert match_exhibit_filename("y29718exv99w1.htm") == (1, "mangled")
    assert match_exhibit_filename("dex991.htm") == (1, "modern")


def test_non_exhibits_and_indexes_do_not_match() -> None:
    """Primary documents and index pages are never exhibit candidates."""
    assert match_exhibit_filename("aapl-20230930.htm") is None
    assert match_exhibit_filename("index.html") is None
    assert match_exhibit_filename("0001-index.html") is None
    assert match_exhibit_filename("R2.htm") is None


def test_selection_ignores_icon_token_types() -> None:
    """Index ``type`` values are icon tokens and never gate selection."""
    picked = select_exhibit_candidates(
        (("ex99-1.htm", "text.gif"), ("exhibit992.htm", "image2.gif"))
    )
    assert [c.filename for c in picked] == ["ex99-1.htm", "exhibit992.htm"]


def test_selection_orders_by_exhibit_number() -> None:
    """EX-99.1 is proposed before later EX-99 exhibits."""
    picked = select_exhibit_candidates(
        (("exhibit993.htm", "EX-99.3"), ("exhibit992.htm", "EX-99.2"))
    )
    assert [c.exhibit_number for c in picked] == [2, 3]


def test_classify_kind_by_extension() -> None:
    """Extensions classify payloads; unknown extensions are text."""
    assert classify_kind("ex99-1.htm") == "html"
    assert classify_kind("ex991.pdf") == "pdf"
    assert classify_kind("ex99-1img001.jpg") == "image"
    assert classify_kind("form8k-ex99.txt") == "text"
