"""Tests for the Stage-1 HTML pre-cleaning module."""

from __future__ import annotations

from defs.text import (
    clean_html_for_parsing,
    strip_benign_font_styles,
    strip_ixbrl_inline_tags,
    strip_office_metadata_attributes,
)


def test_strip_ixbrl_inline_tags_keeps_inner_text() -> None:
    text = (
        '<ix:nonFraction contextref="c-1" unitref="USD" scale="3" '
        'decimals="-3" sign="-">1,234</ix:nonFraction>'
    )
    assert strip_ixbrl_inline_tags(text) == "1,234"


def test_strip_ixbrl_header_block_removed_whole() -> None:
    text = (
        '<ix:header><ix:references><xbrli:context id="c-1">'
        '<xbrli:identifier scheme="http://xbrl/sec">0000000000</xbrli:identifier>'
        "</xbrli:context></ix:references></ix:header>"
        "<p>Body</p>"
    )
    cleaned = strip_ixbrl_inline_tags(text)
    assert "ix:" not in cleaned
    assert "0000000000" not in cleaned
    assert "<p>Body</p>" in cleaned


def test_strip_benign_font_styles_removes_standard_families() -> None:
    text = '<p style="FONT-FAMILY: Times New Roman; TEXT-ALIGN: center">x</p>'
    cleaned = strip_benign_font_styles(text)
    assert "Times New Roman" not in cleaned
    assert "TEXT-ALIGN: center" in cleaned


def test_strip_benign_font_styles_preserves_symbolic_fonts() -> None:
    for family in ("Wingdings", "Webdings", "Symbol"):
        text = f'<p style="FONT-FAMILY: {family}; FONT-SIZE: 10pt">&nbsp;</p>'
        cleaned = strip_benign_font_styles(text)
        assert family in cleaned
        assert "FONT-SIZE" not in cleaned


def test_strip_benign_font_styles_preserves_structure_declarations() -> None:
    text = (
        '<td style="border-top: 1pt solid #000000; WIDTH: 50%; '
        'text-align: right; font-size: 8pt; color: #000000">v</td>'
    )
    cleaned = strip_benign_font_styles(text)
    assert "border-top" in cleaned
    assert "WIDTH: 50%" in cleaned
    assert "text-align: right" in cleaned
    assert "font-size" not in cleaned
    assert "color" not in cleaned


def test_strip_benign_font_styles_drops_emptied_style_attribute() -> None:
    text = '<p style="FONT-SIZE: 8pt">x</p>'
    cleaned = strip_benign_font_styles(text)
    assert "style" not in cleaned
    assert "<p>x</p>" in cleaned.replace("<p >", "<p>").replace("<p>", "<p>")


def test_strip_office_metadata_attributes() -> None:
    text = (
        '<td mso-number-format="\\@" data-x="1" lang="EN-US" xml:lang="EN-US" '
        'colspan="2">v</td>'
    )
    cleaned = strip_office_metadata_attributes(text)
    assert "mso-" not in cleaned
    assert "data-x" not in cleaned
    assert "lang" not in cleaned
    assert 'colspan="2"' in cleaned


def test_clean_html_for_parsing_composes_passes() -> None:
    text = (
        "<ix:header>meta</ix:header>"
        '<ix:nonNumeric contextref="c">5</ix:nonNumeric>'
        '<p style="FONT-FAMILY: Times New Roman" mso-pagination="none">Page 7</p>'
    )
    cleaned = clean_html_for_parsing(text)
    assert "ix:" not in cleaned
    assert "Times New Roman" not in cleaned
    assert "mso-" not in cleaned
    assert "Page 7" in cleaned


def test_clean_html_for_parsing_is_idempotent() -> None:
    text = (
        '<ix:nonFraction scale="3">99</ix:nonFraction>'
        '<td style="FONT-SIZE: 8pt; font-family: Arial; WIDTH: 20%" '
        'lang="EN">v</td>'
    )
    once = clean_html_for_parsing(text)
    twice = clean_html_for_parsing(once)
    assert once == twice


def test_clean_html_for_parsing_preserves_page_marker_layout() -> None:
    text = (
        '<div id="PGBRK" style="MARGIN-LEFT: 0pt; WIDTH: 100%">'
        '<div id="PN" style="PAGE-BREAK-AFTER: always; WIDTH: 100%">'
        '<div style="WIDTH: 100%; TEXT-ALIGN: center">'
        '<font style="DISPLAY: inline; FONT-SIZE: 10pt; '
        'FONT-FAMILY: Times New Roman">121</font>'
        "</div></div></div>"
    )
    cleaned = clean_html_for_parsing(text)
    assert "121" in cleaned
    assert "PAGE-BREAK-AFTER" in cleaned
    assert "PGBRK" in cleaned
    assert "Times New Roman" not in cleaned


def test_clean_html_for_parsing_performance_bounded() -> None:
    # 50k font-heavy paragraphs must clean in well under a second.
    paragraph = (
        '<p style="FONT-FAMILY: Times New Roman; FONT-SIZE: 8pt" '
        'mso-spacing="auto">Body text.</p>'
    )
    blob = paragraph * 50_000
    import time

    start = time.perf_counter()
    cleaned = clean_html_for_parsing(blob)
    elapsed = time.perf_counter() - start
    assert "Times New Roman" not in cleaned
    assert elapsed < 1.0
