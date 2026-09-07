"""Canonical HTML tag classifications for parsing, tree traversal, and decomposition."""

from __future__ import annotations

# Blocks that represent distinct paragraphs/headings (delimit with double newline \n\n)
PARAGRAPH_TAGS: frozenset[str] = frozenset(
    {"p", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}
)

# Structural container blocks (delimit with single newline \n)
CONTAINER_BLOCK_TAGS: frozenset[str] = frozenset(
    {
        "address",
        "article",
        "aside",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "noscript",
        "ol",
        "section",
        "ul",
    }
)

# Table & preformatted blocks
TABLE_AND_PRE_TAGS: frozenset[str] = frozenset(
    {"table", "tbody", "thead", "tfoot", "tr", "td", "th", "pre"}
)

# All block tags combined
BLOCK_TAGS: frozenset[str] = PARAGRAPH_TAGS | CONTAINER_BLOCK_TAGS | TABLE_AND_PRE_TAGS

# Strictly inline formatting elements (stripped without inserting line breaks)
INLINE_TAGS: frozenset[str] = frozenset(
    {
        "a",
        "abbr",
        "b",
        "big",
        "center",
        "cite",
        "code",
        "del",
        "em",
        "font",
        "i",
        "ins",
        "q",
        "s",
        "small",
        "span",
        "strike",
        "strong",
        "sub",
        "sup",
        "u",
    }
)

__all__ = [
    "BLOCK_TAGS",
    "CONTAINER_BLOCK_TAGS",
    "INLINE_TAGS",
    "PARAGRAPH_TAGS",
    "TABLE_AND_PRE_TAGS",
]
