"""Unit and contract tests for edgar_sec.engine.document.html_cleaner."""

from __future__ import annotations

from edgar_sec.engine.document.html_cleaner import (
    clean_html_for_parsing,
    decompose_html_structures,
    normalize_font_qualified_glyphs,
    strip_benign_font_styles,
    strip_font_tag_and_noise_attributes,
    strip_ixbrl_inline_tags,
    strip_office_metadata_attributes,
    strip_toc_navigation_links,
)


def test_strip_ixbrl_inline_tags_keeps_inner_text() -> None:
    text = (
        '<ix:nonFraction contextref="c-1" unitref="USD" scale="3" '
        'decimals="-3" sign="-">1,234</ix:nonFraction>'
    )
    assert strip_ixbrl_inline_tags(text) == "1,234"


def test_strip_ixbrl_inline_tags_covers_fact_namespaces() -> None:
    text = (
        "<dei:EntityRegistrantName>ACME</dei:EntityRegistrantName>"
        "<us-gaap:Revenue>10</us-gaap:Revenue>"
    )
    assert strip_ixbrl_inline_tags(text) == "ACME10"


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


def test_normalize_font_qualified_glyphs() -> None:
    # Wingdings checkbox glyphs
    html = '<span style="font-family: Wingdings">þ</span>'
    normalized = normalize_font_qualified_glyphs(html)
    assert "[X]" in normalized

    html_unchecked = '<font face="Wingdings">o</font>'
    normalized_unchecked = normalize_font_qualified_glyphs(html_unchecked)
    assert "[ ]" in normalized_unchecked


def test_strip_font_tag_and_noise_attributes() -> None:
    html = '<font size="2" color="#000000" face="Arial">Text</font>'
    cleaned = strip_font_tag_and_noise_attributes(html)
    assert "Arial" not in cleaned
    assert "color" not in cleaned
    assert "size" not in cleaned


def test_strip_toc_navigation_links() -> None:
    html = '<a href="#toc">Table of Contents</a>'
    cleaned = strip_toc_navigation_links(html)
    assert "href" not in cleaned


def test_strip_non_displaying_blocks() -> None:
    html = (
        "<html><head><title>Document Title</title><style>.a{color:red;}</style></head>"
        "<body><script>var x=1;</script><noscript>No JS</noscript><p>Visible content</p></body></html>"
    )
    cleaned = clean_html_for_parsing(html)
    assert "Document Title" not in cleaned
    assert "color:red" not in cleaned
    assert "var x=1" not in cleaned
    assert "No JS" not in cleaned
    assert "Visible content" in cleaned


def test_decompose_html_structures() -> None:
    html = "<p>First paragraph.</p><p>Second paragraph.</p>"
    text = decompose_html_structures(html)
    assert "First paragraph.\n\nSecond paragraph." == text
