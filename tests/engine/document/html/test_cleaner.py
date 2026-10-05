"""HTML cleaner passes.
Every pass is a lossy filter whose value is the set of things it refuses to
strip, so preservation cases are pinned alongside the removals.
"""

from __future__ import annotations

from edgar_sec.engine.document.html.cleaner import (
    clean_html_for_parsing,
    normalize_font_qualified_glyphs,
    strip_benign_font_styles,
    strip_font_tag_and_noise_attributes,
    strip_ixbrl_inline_tags,
    strip_non_displaying_blocks,
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


def test_strip_ixbrl_inline_tags_passes_text_without_colons_through() -> None:
    assert strip_ixbrl_inline_tags("<p>plain</p>") == "<p>plain</p>"
    assert strip_ixbrl_inline_tags("") == ""


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


def test_strip_benign_font_styles_strips_margin_and_typography() -> None:
    text = '<p style="margin-left:10pt;padding:2pt;line-height:1.5;float:left">x</p>'
    cleaned = strip_benign_font_styles(text)
    for gone in ("margin-left", "padding", "line-height", "float"):
        assert gone not in cleaned


def test_strip_benign_font_styles_leaves_display_none_alone() -> None:
    text = '<p style="display:none;margin-left:10pt">x</p>'
    cleaned = strip_benign_font_styles(text)
    assert "display:none" in cleaned
    assert "margin-left" not in cleaned


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
    normalized = normalize_font_qualified_glyphs(
        '<span style="font-family: Wingdings">þ</span>'
    )
    assert "[X]" in normalized

    normalized_unchecked = normalize_font_qualified_glyphs(
        '<font face="Wingdings">o</font>'
    )
    assert "[ ]" in normalized_unchecked


def test_normalize_font_qualified_glyphs_leaves_ordinary_fonts_alone() -> None:
    text = '<p style="font-family: Arial">Quarterly results</p>'
    assert normalize_font_qualified_glyphs(text) == text


def test_normalize_font_qualified_glyphs_respects_nested_font_override() -> None:
    html = '<div style="font-family: Wingdings"><span style="font-family: Arial">r</span></div>'
    assert "[X]" not in normalize_font_qualified_glyphs(html)
    assert "[ ]" not in normalize_font_qualified_glyphs(html)


def test_normalize_font_qualified_glyphs_does_not_double_expand_brackets() -> None:
    html = '<span style="font-family: Wingdings">[X]</span>'
    assert "[[X]]" not in normalize_font_qualified_glyphs(html)


def test_normalize_font_qualified_glyphs_ignores_script_and_style_bodies() -> None:
    html = '<style style="font-family: Wingdings">r</style>'
    assert normalize_font_qualified_glyphs(html) == html


def test_strip_font_tag_and_noise_attributes() -> None:
    html = '<font size="2" color="#000000" face="Arial">Text</font>'
    cleaned = strip_font_tag_and_noise_attributes(html)
    assert "Arial" not in cleaned
    assert "color" not in cleaned
    assert "size" not in cleaned


def test_strip_font_tag_preserves_symbolic_face() -> None:
    html = '<font face="Wingdings" size="2">Text</font>'
    cleaned = strip_font_tag_and_noise_attributes(html)
    assert "Wingdings" in cleaned
    assert "size" not in cleaned


def test_strip_font_tag_strips_noise_attributes() -> None:
    html = '<a href="x" tabindex="0" target="_blank">link</a>'
    cleaned = strip_font_tag_and_noise_attributes(html)
    assert "tabindex" not in cleaned
    assert "target" not in cleaned
    assert 'href="x"' in cleaned


def test_strip_toc_navigation_links() -> None:
    html = '<a href="#toc">Table of Contents</a>'
    cleaned = strip_toc_navigation_links(html)
    assert "href" not in cleaned


def test_strip_toc_navigation_links_spares_real_links() -> None:
    html = '<a href="https://www.sec.gov">Filings</a>'
    assert strip_toc_navigation_links(html) == html


def test_strip_non_displaying_blocks() -> None:
    html = (
        "<html><head><title>Document Title</title><style>.a{color:red;}</style></head>"
        "<body><script>var x=1;</script><p>Visible content</p></body></html>"
    )
    cleaned = strip_non_displaying_blocks(html)
    assert "Document Title" not in cleaned
    assert "color:red" not in cleaned
    assert "var x=1" not in cleaned
    assert "Visible content" in cleaned


def test_clean_html_for_parsing_sanitizes_unicode_whitespace() -> None:
    """A non-breaking space becomes an ASCII space; a zero-width space goes."""
    nbsp = "\u00a0"
    zero_width = "\u200b"
    cleaned = clean_html_for_parsing(f"<p>a{nbsp}b{zero_width}c</p>")
    assert nbsp not in cleaned
    assert zero_width not in cleaned
    assert cleaned == "<p>a bc</p>"


def test_clean_html_for_parsing_preserves_text_content() -> None:
    html = '<p style="FONT-SIZE:9pt">Revenue was $1,000.</p>'
    cleaned = clean_html_for_parsing(html)
    assert "Revenue was $1,000." in cleaned


def test_clean_html_for_parsing_on_empty_input() -> None:
    assert clean_html_for_parsing("") == ""
