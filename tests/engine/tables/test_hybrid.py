"""Unit tests for hybrid <pre> discriminator and text normalizer."""

from __future__ import annotations

from edgar_sec.engine.document.html import parse_html
from edgar_sec.engine.tables.hybrid import (
    PreBlockKind,
    classify_pre_block,
    normalize_hybrid_pre_text,
    restore_hybrid_pre_text,
)


def test_classify_monospace_text_in_pre() -> None:
    html = """
    <pre>
    Year       2023      2022
    -------    -------   -------
    Revenue    1,000     900
    </pre>
    """
    tree = parse_html(html)
    pre_node = tree.css_first("pre")
    assert pre_node is not None
    assert classify_pre_block(pre_node) == PreBlockKind.MONOSPACE_TEXT


def test_classify_sgml_table_in_pre() -> None:
    html = """
    <pre>
    <TABLE>
    <S>                 <C>
    Item                Value
    </TABLE>
    </pre>
    """
    tree = parse_html(html)
    pre_node = tree.css_first("pre")
    assert pre_node is not None
    assert classify_pre_block(pre_node) == PreBlockKind.SGML_TABLE


def test_normalize_and_restore_hybrid_pre_text() -> None:
    text = (
        "Heading\n"
        "<pre>\n"
        "  Year      2023     2022\n"
        "  ------    ----     ----\n"
        "  Net     1,234     1,111\n"
        "</pre>\n"
        "Trailing prose"
    )
    hybrid = normalize_hybrid_pre_text(text)
    assert hybrid.protected
    assert "__SEC_HYBRID_PRE_" in hybrid.text
    restored = restore_hybrid_pre_text(hybrid.text, hybrid.protected)
    assert "Net     1,234     1,111" in restored
